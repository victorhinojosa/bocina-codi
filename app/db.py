"""Base de datos SQLite: tablas, migraciones y el QR fijo de las variables de entorno."""

import logging
import os
import sqlite3
from pathlib import Path

from app import config

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

-- Cuentas: un negocio (merchant) tiene una CLABE registrada en pey, una o más tiendas y sus personas.
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    phone TEXT NOT NULL UNIQUE,       -- 10 dígitos; es el usuario para entrar
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,           -- scrypt; nunca el PIN
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS merchants (
    id TEXT PRIMARY KEY,
    business_name TEXT NOT NULL,      -- lo que ve el cliente al pagar
    legal_name TEXT NOT NULL,         -- titular de la CLABE (se manda a pey como `name`)
    clabe TEXT,
    bank_name TEXT,
    deposit_label TEXT,               -- 'BBVA ···· 2702'
    pey_bank_account_id TEXT UNIQUE,  -- NULL = cuenta CoDi de la API key (solo el negocio demo)
    codi_status TEXT NOT NULL,        -- PENDING | PROCESSING | ACTIVE | ERROR
    codi_error TEXT,
    codi_checked_at INTEGER,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stores (
    id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    user_id TEXT NOT NULL REFERENCES users(id),
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    role TEXT NOT NULL,               -- owner (seller vendrá después)
    PRIMARY KEY (user_id, merchant_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,      -- sha256 del token de la cookie
    user_id TEXT NOT NULL REFERENCES users(id),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    token_hash TEXT PRIMARY KEY,      -- bocina vinculada a una tienda (sin usuario)
    store_id TEXT NOT NULL REFERENCES stores(id),
    created_at INTEGER NOT NULL,
    last_seen INTEGER
);
CREATE TABLE IF NOT EXISTS pair_codes (
    code TEXT PRIMARY KEY,            -- 6 dígitos que muestra la bocina
    poll_hash TEXT NOT NULL UNIQUE,   -- secreto de la bocina para preguntar si ya la vincularon
    store_id TEXT,
    device_token TEXT,                -- se entrega una sola vez a la bocina y se borra
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
    key TEXT NOT NULL,                -- 'phone:5512345678' o 'ip:1.2.3.4' o 'signup:1.2.3.4'
    at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS login_attempts_key ON login_attempts(key, at);
CREATE TABLE IF NOT EXISTS push_sends (
    merchant_id TEXT NOT NULL,
    session_hash TEXT,
    at INTEGER NOT NULL
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
        conn.execute("PRAGMA journal_mode=WAL")  # lecturas (pantallas) no esperan a escrituras (webhooks)
        conn.executescript(SCHEMA)
        # Migraciones (agrega columnas si faltan)
        _add_columns(conn, "charges", {
            "kind": "TEXT NOT NULL DEFAULT 'amount'",
            "qr_string": "TEXT",
            "phone": "TEXT",      # cobro al celular: número del cliente
            "sale_id": "TEXT",    # venta a la que pertenece (para detectar pagos dobles)
            "merchant_id": "TEXT",
            "store_id": "TEXT",
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
            "merchant_id": "TEXT",
            "store_id": "TEXT",
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


def storage_is_persistent() -> bool:
    """¿El historial sobrevive a un nuevo despliegue? En Railway solo si la base vive en un volumen montado."""
    if not os.getenv("RAILWAY_ENVIRONMENT") and not os.getenv("RAILWAY_ENVIRONMENT_NAME"):
        return True  # en tu compu el archivo se queda donde está
    mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")
    return bool(mount) and str(Path(config.DB_PATH).resolve()).startswith(str(Path(mount).resolve()))


def fixed_row(store_id: str | None):
    """QR fijo activo de una tienda."""
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM charges WHERE kind='fixed' AND status='active' AND store_id IS ? ORDER BY created_at DESC LIMIT 1",
            (store_id,),
        ).fetchone()
