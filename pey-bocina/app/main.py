"""
Bocina CoDi — punto de venta con confirmación de pago por voz.

Flujo:
  1. El comercio crea un cobro  -> POST /api/charges  -> pey POST /codi/qr
  2. Se muestra el QR (SVG generado aquí a partir de qrString)
  3. El cliente paga desde su app bancaria
  4. pey manda el webhook       -> POST /webhooks/pey (firma verificada con Standard Webhooks)
  5. El backend avisa al navegador por SSE -> la bocina dice "Recibiste cien pesos"

La confirmación SOLO sale de un webhook con firma válida. Nada que venga del navegador
puede marcar un cobro como pagado (salvo el modo simulación, que va etiquetado y
desactivado por defecto).
"""

import asyncio
import json
import logging
import os
import random
import re
import sqlite3
import time
from pathlib import Path

import httpx
import segno
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from num2words import num2words
from pydantic import BaseModel, Field
from standardwebhooks.webhooks import Webhook

load_dotenv()

# ---------------------------------------------------------------------------
# Config (todo vive en el servidor; las llaves nunca llegan al navegador)
# ---------------------------------------------------------------------------
PEY_API_KEY = os.getenv("PEY_API_KEY", "")
PEY_BASE_URL = os.getenv("PEY_BASE_URL", "https://api.pey.mx").rstrip("/")
PEY_WEBHOOK_SECRET = os.getenv("PEY_WEBHOOK_SECRET", "")  # whsec_...
DEFAULT_EXPIRATION = int(os.getenv("DEFAULT_EXPIRATION", "0"))  # segundos; 0 = el valor que probaste

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")

ALLOW_SIMULATION = os.getenv("ALLOW_SIMULATION", "false").lower() == "true"
DB_PATH = os.getenv("DB_PATH", str(Path(__file__).resolve().parent.parent / "bocina.db"))

STATIC_DIR = Path(__file__).resolve().parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bocina")

app = FastAPI(title="Bocina CoDi")


# ---------------------------------------------------------------------------
# Base de datos (SQLite: suficiente para el MVP)
# ---------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS charges (
                id TEXT PRIMARY KEY,          -- id de pey = IDC de Banxico = codiQrId del webhook
                amount REAL NOT NULL,
                concept TEXT NOT NULL,
                num_ref TEXT NOT NULL,
                status TEXT NOT NULL,         -- pending | paid
                created_at INTEGER NOT NULL,
                expiration INTEGER NOT NULL,
                paid_at INTEGER,
                paid_amount REAL,
                transaction_id TEXT,
                simulated INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS webhook_events (
                webhook_id TEXT PRIMARY KEY,  -- clave de idempotencia (header webhook-id)
                received_at INTEGER NOT NULL,
                type TEXT,
                payload TEXT NOT NULL
            );
            """
        )


init_db()


def charge_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "amount": row["amount"],
        "concept": row["concept"],
        "numRef": row["num_ref"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "expiration": row["expiration"],
        "paidAt": row["paid_at"],
        "paidAmount": row["paid_amount"],
        "transactionId": row["transaction_id"],
        "simulated": bool(row["simulated"]),
    }


# ---------------------------------------------------------------------------
# SSE: avisar a todas las pantallas/bocinas abiertas
# ---------------------------------------------------------------------------
class Broadcaster:
    def __init__(self) -> None:
        self.queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.queues.discard(q)

    async def publish(self, event: dict) -> None:
        for q in list(self.queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


bus = Broadcaster()


# ---------------------------------------------------------------------------
# Texto hablado: "Recibiste ciento veintiún pesos con cincuenta centavos"
# ---------------------------------------------------------------------------
def _words(n: int) -> str:
    w = num2words(n, lang="es")
    # apócope antes de sustantivo: veintiuno -> veintiún, ciento uno -> ciento un
    if w.endswith("veintiuno"):
        return w[: -len("veintiuno")] + "veintiún"
    if w == "uno" or w.endswith(" uno"):
        return w[:-3] + "un"
    return w


def speech_for_amount(amount: float, simulated: bool = False) -> str:
    cents = round(float(amount) * 100)
    pesos, cent = divmod(cents, 100)
    parts = []
    if pesos:
        parts.append(f"{_words(pesos)} {'peso' if pesos == 1 else 'pesos'}")
    if cent:
        parts.append(f"{_words(cent)} {'centavo' if cent == 1 else 'centavos'}")
    text = "Recibiste " + " con ".join(parts) if parts else "Recibiste un pago"
    return f"Simulación. {text}" if simulated else text


# ---------------------------------------------------------------------------
# API: estado / config
# ---------------------------------------------------------------------------
@app.get("/api/status")
async def status() -> dict:
    return {
        "pey": bool(PEY_API_KEY),
        "webhookSecret": bool(PEY_WEBHOOK_SECRET),
        "elevenlabs": bool(ELEVENLABS_API_KEY),
        "claude": bool(ANTHROPIC_API_KEY),
        "allowSimulation": ALLOW_SIMULATION,
        "defaultExpiration": DEFAULT_EXPIRATION,
        "webhookPath": "/webhooks/pey",
    }


# ---------------------------------------------------------------------------
# API: cobros
# ---------------------------------------------------------------------------
class ChargeIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    concept: str = Field(default="Venta", min_length=1, max_length=100)
    expiration: int | None = Field(default=None, ge=0)


@app.post("/api/charges")
async def create_charge(body: ChargeIn) -> dict:
    if not PEY_API_KEY:
        raise HTTPException(400, "Falta PEY_API_KEY en el .env")

    amount = round(body.amount, 2)
    expiration = DEFAULT_EXPIRATION if body.expiration is None else body.expiration
    num_ref = str(random.randint(1, 9_999_999))  # referencia numérica (hasta 7 dígitos)

    payload = {
        "amount": amount,
        "concept": body.concept.strip(),
        "expiration": expiration,
        "numRef": num_ref,
        "generateImage": False,
        "metadata": {},
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{PEY_BASE_URL}/codi/qr",
                headers={"Authorization": f"Bearer {PEY_API_KEY}"},
                json=payload,
            )
    except httpx.HTTPError as e:
        log.exception("Error de red con pey")
        raise HTTPException(502, f"No se pudo contactar a pey: {e}") from e

    if r.status_code >= 400:
        log.warning("pey respondió %s: %s", r.status_code, r.text[:500])
        raise HTTPException(502, f"pey respondió {r.status_code}: {r.text[:300]}")

    data = r.json()
    qr_id, qr_string = data.get("id"), data.get("qrString")
    if not qr_id or not qr_string:
        raise HTTPException(502, f"Respuesta inesperada de pey: {str(data)[:300]}")

    now = int(time.time())
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO charges (id, amount, concept, num_ref, status, created_at, expiration)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (qr_id, amount, payload["concept"], num_ref, now, expiration),
        )

    # omitsize=True -> el SVG lleva viewBox y escala completo (sin esto el CSS lo recortaba).
    # border=4 es la zona blanca estándar que piden los lectores de QR.
    svg = segno.make(qr_string, error="m").svg_inline(
        scale=6, border=4, dark="#000000", light="#ffffff", omitsize=True
    )
    log.info("Cobro creado %s por $%.2f (%s)", qr_id, amount, payload["concept"])
    return {
        "id": qr_id,
        "amount": amount,
        "concept": payload["concept"],
        "numRef": num_ref,
        "expiration": expiration,
        "createdAt": now,
        "qrSvg": svg,
    }


@app.get("/api/charges")
async def list_charges(limit: int = 50) -> dict:
    start_of_day = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM charges ORDER BY created_at DESC LIMIT ?", (min(limit, 200),)
        ).fetchall()
        total = conn.execute(
            "SELECT COALESCE(SUM(paid_amount), 0), COUNT(*) FROM charges"
            " WHERE status='paid' AND simulated=0 AND paid_at >= ?",
            (start_of_day,),
        ).fetchone()
    return {
        "charges": [charge_to_dict(r) for r in rows],
        "todayTotal": round(total[0], 2),
        "todayCount": total[1],
    }


@app.get("/api/charges/{charge_id}")
async def get_charge(charge_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM charges WHERE id = ?", (charge_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Cobro no encontrado")
    return charge_to_dict(row)


# ---------------------------------------------------------------------------
# Webhook de pey: LA fuente de verdad del pago
# ---------------------------------------------------------------------------
async def handle_payment(payload: dict, *, simulated: bool = False) -> dict:
    qr_id = payload.get("codiQrId")
    amount = float(payload.get("amount") or 0)
    paid_at = int(payload.get("datePaid") or time.time())
    tx_id = payload.get("transactionId")

    with db() as conn:
        row = conn.execute("SELECT * FROM charges WHERE id = ?", (qr_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE charges SET status='paid', paid_at=?, paid_amount=?, transaction_id=?, simulated=?"
                " WHERE id=?",
                (paid_at, amount, tx_id, int(simulated), qr_id),
            )

    event = {
        "type": "payment",
        "verified": not simulated,
        "simulated": simulated,
        "chargeId": qr_id,
        "matched": bool(row),  # False = pago a un QR que no creó esta app (p. ej. desde Postman)
        "amount": amount,
        "expectedAmount": row["amount"] if row else None,
        "concept": payload.get("concept") or (row["concept"] if row else ""),
        "transactionId": tx_id,
        "datePaid": paid_at,
        "speech": speech_for_amount(amount, simulated),
    }
    await bus.publish(event)
    log.info("PAGO %s: $%.2f qr=%s tx=%s", "SIMULADO" if simulated else "VERIFICADO", amount, qr_id, tx_id)
    return event


@app.post("/webhooks/pey")
async def pey_webhook(request: Request) -> JSONResponse:
    raw = (await request.body()).decode("utf-8")
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not PEY_WEBHOOK_SECRET:
        log.error("Llegó un webhook pero falta PEY_WEBHOOK_SECRET; no se puede verificar")
        return JSONResponse({"error": "webhook secret not configured"}, status_code=503)

    # 1) Verificar firma sobre el cuerpo crudo (no sobre el JSON parseado)
    try:
        Webhook(PEY_WEBHOOK_SECRET).verify(raw, headers)
    except Exception as e:  # firma inválida, timestamp viejo, headers faltantes
        log.warning("Webhook rechazado (firma inválida): %s", e)
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    # 2) Idempotencia: pey puede reintentar; el mismo webhook-id solo cuenta una vez
    webhook_id = headers.get("webhook-id") or f"noid-{time.time_ns()}"
    payload = json.loads(raw)
    event_type = payload.get("type", "")
    with db() as conn:
        dup = conn.execute("SELECT 1 FROM webhook_events WHERE webhook_id=?", (webhook_id,)).fetchone()
        if dup:
            log.info("Webhook duplicado ignorado: %s", webhook_id)
            return JSONResponse({"ok": True, "duplicate": True})
        conn.execute(
            "INSERT INTO webhook_events (webhook_id, received_at, type, payload) VALUES (?, ?, ?, ?)",
            (webhook_id, int(time.time()), event_type, raw),
        )

    # 3) Procesar
    if event_type == "codi.qr.payment_received":
        await handle_payment(payload)
    else:
        log.info("Webhook %s recibido (sin manejador): %s", event_type, raw[:300])

    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# SSE: el navegador escucha aquí
# ---------------------------------------------------------------------------
@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    q = bus.subscribe()

    async def stream():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # mantiene viva la conexión a través de túneles/proxies
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Voz: TTS con ElevenLabs (la llave se queda en el servidor)
# ---------------------------------------------------------------------------
class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)


_tts_cache: dict[str, bytes] = {}


@app.post("/api/tts")
async def tts(body: TTSIn) -> Response:
    if not ELEVENLABS_API_KEY:
        raise HTTPException(400, "Falta ELEVENLABS_API_KEY")
    key = f"{ELEVENLABS_VOICE_ID}:{body.text}"
    if key not in _tts_cache:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": ELEVENLABS_API_KEY},
                json={"text": body.text, "model_id": ELEVENLABS_MODEL, "language_code": "es"},
            )
        if r.status_code >= 400:
            log.warning("ElevenLabs %s: %s", r.status_code, r.text[:300])
            raise HTTPException(502, "ElevenLabs falló")
        if len(_tts_cache) > 300:
            _tts_cache.clear()
        _tts_cache[key] = r.content
    return Response(_tts_cache[key], media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# Voz: entender "cóbrale ochenta y cinco de dos tortas"
# ---------------------------------------------------------------------------
class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


PARSE_SYSTEM = (
    "Eres el punto de venta de una tiendita en México. Te paso lo que dijo el tendero para cobrar. "
    "Extrae el monto total en pesos mexicanos y un concepto corto. Si menciona cantidad y precio unitario, "
    "multiplica. Responde SOLO con JSON, sin texto extra: "
    '{"amount": number o null, "concept": "texto corto"}. '
    'Ejemplos: "cóbrale ochenta y cinco" -> {"amount": 85, "concept": "Venta"}; '
    '"dos tortas de cuarenta y cinco" -> {"amount": 90, "concept": "2 tortas"}; '
    '"un refresco, veinte pesos cincuenta" -> {"amount": 20.5, "concept": "Refresco"}.'
)


def regex_parse(text: str) -> dict:
    m = re.search(r"\$?\s*(\d+(?:[.,]\d{1,2})?)", text)
    amount = float(m.group(1).replace(",", ".")) if m else None
    return {"amount": amount, "concept": "Venta", "source": "regex"}


@app.post("/api/parse")
async def parse(body: ParseIn) -> dict:
    if not ANTHROPIC_API_KEY:
        return regex_parse(body.text)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 150,
                    "system": PARSE_SYSTEM,
                    "messages": [{"role": "user", "content": body.text}],
                },
            )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        data = json.loads(text[text.find("{") : text.rfind("}") + 1])
        amount = data.get("amount")
        return {
            "amount": round(float(amount), 2) if amount else None,
            "concept": (data.get("concept") or "Venta")[:100],
            "source": "claude",
        }
    except Exception as e:
        log.warning("Claude parse falló, uso regex: %s", e)
        return regex_parse(body.text)


# ---------------------------------------------------------------------------
# Simulación (solo para probar la UI sin gastar; desactivada por defecto)
# ---------------------------------------------------------------------------
@app.post("/api/dev/simulate/{charge_id}")
async def simulate(charge_id: str) -> dict:
    if not ALLOW_SIMULATION:
        raise HTTPException(403, "Simulación desactivada (ALLOW_SIMULATION=false)")
    with db() as conn:
        row = conn.execute("SELECT * FROM charges WHERE id = ?", (charge_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Cobro no encontrado")
    payload = {
        "type": "codi.qr.payment_received",
        "codiQrId": charge_id,
        "amount": row["amount"],
        "concept": row["concept"],
        "datePaid": int(time.time()),
        "transactionId": f"SIM-{time.time_ns()}",
    }
    return await handle_payment(payload, simulated=True)


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
