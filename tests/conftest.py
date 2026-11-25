import asyncio
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Nunca usar las llaves reales del .env en las pruebas (load_dotenv no pisa variables ya definidas)
for name in ("PEY_API_KEY", "PEY_WEBHOOK_SECRET", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FIXED_QR_ID",
             "FIXED_QR_STRING", "ADMIN_PIN"):
    os.environ[name] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from standardwebhooks.webhooks import Webhook  # noqa: E402

from app import config, timeutil  # noqa: E402
from app.db import connect  # noqa: E402
from app.events import bus  # noqa: E402

SECRET = "whsec_" + base64.b64encode(b"bocina-test-secret-32-bytes-long").decode()
NOW = 1795600000  # 2026-11-25 01:06:40 UTC = 2026-11-24 19:06:40 en Ciudad de México


@pytest.fixture
def clock(monkeypatch):
    """Reloj fijo y controlable: clock.now += 60 avanza un minuto."""
    class Clock:
        now = NOW
    c = Clock()
    monkeypatch.setattr(timeutil, "now_ts", lambda: c.now)
    return c


@pytest.fixture
def client(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "PEY_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(config, "PEY_API_KEY", "test-key")
    monkeypatch.setattr(config, "PEY_BASE_URL", "http://pey.invalid")  # ninguna llamada real a pey
    monkeypatch.setattr(config, "RECOVERY_POLL_SECONDS", 0)  # el ciclo de fondo no corre; las pruebas llaman poll_once
    monkeypatch.setattr(config, "BUSINESS_TZ", "America/Mexico_City")
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def events():
    """Eventos que el servidor manda a las pantallas por SSE."""
    q = bus.subscribe()

    def drain() -> list[dict]:
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out

    yield drain
    bus.unsubscribe(q)


def sign_and_post(client, payload: dict, *, webhook_id: str = "msg_1", secret: str = SECRET, ts: datetime | None = None):
    body = json.dumps(payload)
    ts = ts or datetime.now(timezone.utc)
    sig = Webhook(secret).sign(webhook_id, ts, body)
    headers = {"webhook-id": webhook_id, "webhook-timestamp": str(int(ts.timestamp())),
               "webhook-signature": sig, "content-type": "application/json"}
    return client.post("/webhooks/pey", content=body, headers=headers)


def qr_payment(tx_id: str, amount: float, *, qr_id: str = "QRFIJO", paid_at: int = NOW, **extra) -> dict:
    return {"type": "codi.qr.payment_received", "transactionId": tx_id, "codiQrId": qr_id, "amount": amount,
            "datePaid": paid_at, "concept": "Mi tienda", "numRef": "1",
            "metadata": {"bankCode": 40014, "clabe": "014180000000006460", "trackingKey": "TRK" + tx_id}, **extra}


def add_charge(id: str, *, kind: str, amount: float = 0, status: str | None = None, sale_id: str | None = None,
               created_at: int = NOW - 60, phone: str | None = None) -> None:
    status = status or {"fixed": "active"}.get(kind, "pending")
    with connect() as conn:
        conn.execute(
            "INSERT INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, qr_string, phone, sale_id)"
            " VALUES (?, ?, 'Venta', '1', ?, ?, ?, ?, 'QRSTRING', ?, ?)",
            (id, amount, status, created_at, 900 if kind == "push" else 0, kind, phone, sale_id or id),
        )


def payment(tx_id: str):
    with connect() as conn:
        return conn.execute("SELECT * FROM payments WHERE transaction_id=?", (tx_id,)).fetchone()


def count(table: str) -> int:
    with connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def run(coro):
    return asyncio.run(coro)
