"""Negocios: alta con su CLABE en pey, activación en CoDi y la cuenta demo."""

import logging
import re
import sqlite3

from app import auth, config, pey, timeutil
from app.db import connect
from app.events import bus
from app.payments import BANKS

log = logging.getLogger("bocina")

# prefijo de 3 dígitos de la CLABE -> banco (los códigos de BANKS terminan en ese prefijo)
CLABE_BANKS = {code[-3:]: name for code, name in BANKS.items()}
STATUS_CHECK_EVERY = 60  # segundos entre consultas a pey mientras la cuenta se activa


def clabe_problem(clabe: str) -> str | None:
    """Motivo si la CLABE no es válida (18 dígitos y dígito verificador de Banxico); None si está bien."""
    if not re.fullmatch(r"\d{18}", clabe or ""):
        return "La CLABE debe tener 18 dígitos."
    weights = (3, 7, 1) * 6
    total = sum((int(d) * w) % 10 for d, w in zip(clabe[:17], weights))
    if (10 - total % 10) % 10 != int(clabe[17]):
        return "Esa CLABE no es válida. Revisa los 18 dígitos."
    return None


def bank_for_clabe(clabe: str) -> str | None:
    return CLABE_BANKS.get((clabe or "")[:3])


def deposit_label(clabe: str) -> str:
    return f"{bank_for_clabe(clabe) or 'Cuenta'} ···· {clabe[-4:]}"


def merchant_dict(m: sqlite3.Row) -> dict:
    return {
        "id": m["id"], "businessName": m["business_name"], "legalName": m["legal_name"],
        "bank": m["bank_name"], "clabe4": (m["clabe"] or "")[-4:] or None,
        "depositAccount": m["deposit_label"], "codiStatus": m["codi_status"], "codiError": m["codi_error"],
        "isDemo": bool(m["is_demo"]),
    }


def get(merchant_id: str):
    with connect() as conn:
        return conn.execute("SELECT * FROM merchants WHERE id=?", (merchant_id,)).fetchone()


def first_store(merchant_id: str):
    with connect() as conn:
        return conn.execute("SELECT * FROM stores WHERE merchant_id=? ORDER BY created_at LIMIT 1", (merchant_id,)).fetchone()


def create(*, phone: str, pin: str, first_name: str, last_name: str, business_name: str, clabe: str,
           bank_account: dict | None, is_demo: bool = False) -> tuple[str, str]:
    """Crea persona, negocio, tienda y membresía de dueño. Devuelve (user_id, merchant_id)."""
    now = timeutil.now_ts()
    uid, mid, sid = auth.new_id(), auth.new_id(), auth.new_id()
    with connect() as conn:
        conn.execute("INSERT INTO users (id, phone, first_name, last_name, pin_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (uid, phone, first_name, last_name, auth.hash_pin(pin), now))
        conn.execute(
            "INSERT INTO merchants (id, business_name, legal_name, clabe, bank_name, deposit_label, pey_bank_account_id,"
            " codi_status, is_demo, created_at, codi_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, business_name, f"{first_name} {last_name}".strip(), clabe or None, bank_for_clabe(clabe) if clabe else None,
             deposit_label(clabe) if clabe else None, (bank_account or {}).get("id"),
             (bank_account or {}).get("codiStatus") or ("ACTIVE" if is_demo else "PENDING"), int(is_demo), now, now),
        )
        conn.execute("INSERT INTO stores (id, merchant_id, name, created_at) VALUES (?, ?, ?, ?)", (sid, mid, business_name, now))
        conn.execute("INSERT INTO memberships (user_id, merchant_id, role) VALUES (?, ?, 'owner')", (uid, mid))
    return uid, mid


async def ensure_fixed_qr(merchant_id: str) -> None:
    """Cuenta ACTIVE sin QR fijo -> se crea con su bankAccountId. Se llama al activarse y como respaldo."""
    m, store = get(merchant_id), first_store(merchant_id)
    if not m or not store or m["codi_status"] != "ACTIVE":
        return
    with connect() as conn:
        if conn.execute("SELECT 1 FROM charges WHERE kind='fixed' AND status='active' AND store_id=?", (store["id"],)).fetchone():
            return
    if not m["pey_bank_account_id"] and not m["is_demo"]:
        return  # nunca cobrar a nombre de otro negocio en la cuenta de la API key
    qr_id, qr_string, num_ref = await pey.create_qr(0, m["business_name"], 0, m["pey_bank_account_id"])
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, qr_string,"
            " merchant_id, store_id) VALUES (?, 0, ?, ?, 'active', ?, 0, 'fixed', ?, ?, ?)",
            (qr_id, m["business_name"], num_ref, timeutil.now_ts(), qr_string, merchant_id, store["id"]),
        )
    log.info("QR fijo creado para %s (%s)", m["business_name"], qr_id)
    await bus.publish({"type": "fixed"}, merchant_id)


async def set_codi_status(bank_account_id: str, status: str, error: str | None = None) -> str | None:
    """Actualiza el estado de alta. Si pasó a ACTIVE crea el QR fijo y avisa a las pantallas. Devuelve el merchant_id."""
    with connect() as conn:
        m = conn.execute("SELECT * FROM merchants WHERE pey_bank_account_id=?", (bank_account_id,)).fetchone()
        if not m:
            return None
        conn.execute("UPDATE merchants SET codi_status=?, codi_error=?, codi_checked_at=? WHERE id=?",
                     (status, error, timeutil.now_ts(), m["id"]))
    if status != m["codi_status"]:
        log.info("Cuenta de %s: %s -> %s", m["business_name"], m["codi_status"], status)
        await bus.publish({"type": "account", "codiStatus": status}, m["id"])
    if status == "ACTIVE":
        try:
            await ensure_fixed_qr(m["id"])
        except Exception as e:  # se reintenta en la siguiente consulta de /api/me
            log.warning("No se pudo crear el QR fijo de %s: %s", m["business_name"], e)
    return m["id"]


async def refresh_status(m: sqlite3.Row) -> sqlite3.Row:
    """Mientras la cuenta no esté activa, consulta a pey (como mucho cada minuto). Respaldo del webhook."""
    if m["codi_status"] == "ACTIVE":
        try:
            await ensure_fixed_qr(m["id"])
        except Exception as e:
            log.warning("No se pudo crear el QR fijo de %s: %s", m["business_name"], e)
        return m
    if not m["pey_bank_account_id"] or timeutil.now_ts() - (m["codi_checked_at"] or 0) < STATUS_CHECK_EVERY:
        return m
    try:
        acc = await pey.get_bank_account(m["pey_bank_account_id"])
        await set_codi_status(m["pey_bank_account_id"], acc.get("codiStatus") or m["codi_status"], acc.get("errorMessage"))
    except Exception as e:
        log.warning("No se pudo consultar la cuenta de %s en pey: %s", m["business_name"], e)
        with connect() as conn:
            conn.execute("UPDATE merchants SET codi_checked_at=? WHERE id=?", (timeutil.now_ts(), m["id"]))
    return get(m["id"])


def seed_demo() -> None:
    """Cuenta demo (Ramón): se crea con DEMO_PHONE/DEMO_PIN y se queda con los pagos de antes de las cuentas
    (QR fijo de FIXED_QR_ID, cuenta CoDi de la API key). Si cambias DEMO_PIN, se actualiza al arrancar."""
    with connect() as conn:
        demo = conn.execute("SELECT * FROM merchants WHERE is_demo=1 LIMIT 1").fetchone()
        legacy = conn.execute("SELECT 1 FROM charges WHERE merchant_id IS NULL UNION SELECT 1 FROM payments WHERE merchant_id IS NULL").fetchone()
    phone, pin = config.DEMO_PHONE, config.DEMO_PIN
    if not demo and not (phone and pin) and not legacy:
        return
    if not demo:
        if not (phone and pin):  # sin DEMO_PHONE/DEMO_PIN nadie puede entrar (el PIN no es de 6 dígitos)
            phone, pin = phone or "0000000000", auth.new_token()
        uid, mid = create(phone=phone, pin=pin, first_name=config.DEMO_FIRST_NAME, last_name=config.DEMO_LAST_NAME,
                          business_name=config.BUSINESS_NAME, clabe="", bank_account=None, is_demo=True)
        with connect() as conn:
            conn.execute("UPDATE merchants SET deposit_label=? WHERE id=?", (config.DEPOSIT_ACCOUNT_LABEL or None, mid))
        log.info("Cuenta demo creada (%s)", config.BUSINESS_NAME)
    with connect() as conn:
        demo = conn.execute("SELECT * FROM merchants WHERE is_demo=1 LIMIT 1").fetchone()
        store = conn.execute("SELECT * FROM stores WHERE merchant_id=? ORDER BY created_at LIMIT 1", (demo["id"],)).fetchone()
        user = conn.execute("SELECT u.* FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.merchant_id=? AND m.role='owner'",
                            (demo["id"],)).fetchone()
        if config.DEMO_PHONE and config.DEMO_PIN and user:
            if user["phone"] != config.DEMO_PHONE or not auth.check_pin(config.DEMO_PIN, user["pin_hash"]):
                conn.execute("UPDATE users SET phone=?, pin_hash=? WHERE id=?",
                             (config.DEMO_PHONE, auth.hash_pin(config.DEMO_PIN), user["id"]))
        if config.DEPOSIT_ACCOUNT_LABEL:
            conn.execute("UPDATE merchants SET deposit_label=? WHERE id=?", (config.DEPOSIT_ACCOUNT_LABEL, demo["id"]))
        # Todo lo de antes de las cuentas es de la demo
        conn.execute("UPDATE charges SET merchant_id=?, store_id=? WHERE merchant_id IS NULL", (demo["id"], store["id"]))
        conn.execute("UPDATE payments SET merchant_id=?, store_id=? WHERE merchant_id IS NULL", (demo["id"], store["id"]))
        # QR fijo amarrado por variables de entorno
        if config.FIXED_QR_ID and config.FIXED_QR_STRING:
            conn.execute("UPDATE charges SET status='retired' WHERE kind='fixed' AND status='active' AND store_id=? AND id != ?",
                         (store["id"], config.FIXED_QR_ID))
            if conn.execute("SELECT 1 FROM charges WHERE id=?", (config.FIXED_QR_ID,)).fetchone():
                conn.execute("UPDATE charges SET status='active', kind='fixed', qr_string=?, concept=?, merchant_id=?, store_id=?"
                             " WHERE id=?", (config.FIXED_QR_STRING, demo["business_name"], demo["id"], store["id"], config.FIXED_QR_ID))
            else:
                conn.execute(
                    "INSERT INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, qr_string, merchant_id, store_id)"
                    " VALUES (?, 0, ?, '0', 'active', ?, 0, 'fixed', ?, ?, ?)",
                    (config.FIXED_QR_ID, demo["business_name"], timeutil.now_ts(), config.FIXED_QR_STRING, demo["id"], store["id"]),
                )
