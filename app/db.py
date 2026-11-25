"""Base de datos SQLite: tablas, migraciones y el QR fijo de las variables de entorno."""

import logging
import os
import sqlite3
from pathlib import Path

from app import config, timeutil

log = logging.getLogger("bocina")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS charges (
    id TEXT PRIMARY KEY,          -- id de pey = IDC de Banxico = codiQrId del webhook
    amount REAL NOT NULL,         -- 0 en QR fijo
    concept TEXT NOT NULL,
    num_ref TEXT NOT NULL,
    status TEXT NOT NULL,         -- pending | paid (con monto) / active | retired (fijo)
    created_at INTEGER NOT NULL,
    expiration INTEGER NOT NULL,
    paid_at INTEGER,
    paid_amount REAL,
    transaction_id TEXT,
    simulated INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments (
    transaction_id TEXT PRIMARY KEY,  -- id de pey: clave de idempotencia entre webhook y respaldo
    codi_qr_id TEXT,
    kind TEXT,                    -- fixed | amount | push | external
    amount REAL NOT NULL,
    concept TEXT,
    paid_at INTEGER NOT NULL,     -- cuándo se pagó, según pey (datePaid)
    simulated INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS webhook_events (
    webhook_id TEXT PRIMARY KEY,  -- header webhook-id; se guarda solo después de procesarlo bien
    received_at INTEGER NOT NULL,
    type TEXT,
    payload TEXT NOT NULL
);
"""


def _add_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> set[str]:
    existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    added = set()
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            added.add(name)
    return added


def init_db() -> None:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)  # p. ej. el volumen /data en Railway
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Migraciones (agrega columnas si faltan)
        _add_columns(conn, "charges", {
            "kind": "TEXT NOT NULL DEFAULT 'amount'",
            "qr_string": "TEXT",
            "phone": "TEXT",      # cobro al celular: número del cliente
            "sale_id": "TEXT",    # venta a la que pertenece (para detectar pagos dobles)
        })
        added = _add_columns(conn, "payments", {
            "phone4": "TEXT",
            "duplicate_sale": "INTEGER NOT NULL DEFAULT 0",
            # quién pagó (del aviso de pey): banco, últimos 4 de su CLABE y clave de rastreo
            "payer_bank": "TEXT",
            "payer_clabe4": "TEXT",
            "tracking_key": "TEXT",
            "expected_amount": "REAL",  # monto del cobro (con monto / al celular), para marcar si no coincide
            "created_at": "INTEGER",    # cuándo lo registró la app
            "received_at": "INTEGER",   # cuándo llegó el webhook (NULL si solo lo trajo el respaldo)
            "source": "TEXT NOT NULL DEFAULT 'webhook'",  # webhook | recovery | simulation
        })
        if "created_at" in added:
            conn.execute("UPDATE payments SET created_at = paid_at WHERE created_at IS NULL")
            conn.execute("UPDATE payments SET source = 'simulation' WHERE simulated = 1")
            try:  # hora real de llegada desde el registro de webhooks
                conn.execute(
                    "UPDATE payments SET received_at = (SELECT MIN(w.received_at) FROM webhook_events w"
                    " WHERE json_extract(w.payload, '$.transactionId') = payments.transaction_id)"
                    " WHERE received_at IS NULL AND simulated = 0"
                )
            except sqlite3.OperationalError:
                pass  # SQLite sin JSON: se queda vacío
        if "expected_amount" in added:
            conn.execute(
                "UPDATE payments SET expected_amount = (SELECT c.amount FROM charges c WHERE c.id = payments.codi_qr_id)"
                " WHERE kind IN ('amount', 'push')"
            )
        # Pagos viejos -> tabla payments
        conn.execute(
            "INSERT OR IGNORE INTO payments (transaction_id, codi_qr_id, kind, amount, concept, paid_at, simulated, created_at)"
            " SELECT transaction_id, id, 'amount', paid_amount, concept, paid_at, simulated, paid_at FROM charges"
            " WHERE status='paid' AND transaction_id IS NOT NULL"
        )


def seed_fixed_qr() -> None:
    """Si el QR fijo viene en las variables de entorno, lo deja como el QR activo."""
    if not config.FIXED_LOCKED:
        return
    with connect() as conn:
        row = conn.execute("SELECT status FROM charges WHERE id = ?", (config.FIXED_QR_ID,)).fetchone()
        conn.execute("UPDATE charges SET status='retired' WHERE kind='fixed' AND status='active' AND id != ?",
                     (config.FIXED_QR_ID,))
        if row:
            conn.execute("UPDATE charges SET status='active', kind='fixed', qr_string=?, concept=? WHERE id=?",
                         (config.FIXED_QR_STRING, config.BUSINESS_NAME, config.FIXED_QR_ID))
        else:
            conn.execute(
                "INSERT INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, qr_string)"
                " VALUES (?, 0, ?, '0', 'active', ?, 0, 'fixed', ?)",
                (config.FIXED_QR_ID, config.BUSINESS_NAME, timeutil.now_ts(), config.FIXED_QR_STRING),
            )


def storage_is_persistent() -> bool:
    """¿El historial sobrevive a un nuevo despliegue? En Railway solo si la base vive en un volumen montado."""
    if not os.getenv("RAILWAY_ENVIRONMENT") and not os.getenv("RAILWAY_ENVIRONMENT_NAME"):
        return True  # en tu compu el archivo se queda donde está
    mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")
    return bool(mount) and str(Path(config.DB_PATH).resolve()).startswith(str(Path(mount).resolve()))


def fixed_row():
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM charges WHERE kind='fixed' AND status='active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
