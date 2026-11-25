"""Registrar pagos (webhook, respaldo o simulación), anunciarlos y armar el historial."""

import logging
import re
import sqlite3

from app import config, timeutil
from app.db import connect
from app.events import bus
from app.speech import amount_letters, speech_for_amount

log = logging.getLogger("bocina")

# Bancos más comunes en SPEI/CoDi (código de 5 dígitos que manda pey y prefijo de 3 dígitos de la CLABE)
BANKS = {
    "40002": "Banamex", "40012": "BBVA", "40014": "Santander", "40021": "HSBC", "40030": "BanBajío",
    "40036": "Inbursa", "40042": "Mifel", "40044": "Scotiabank", "40058": "Banregio", "40062": "Afirme",
    "40072": "Banorte", "40127": "Banco Azteca", "40130": "Compartamos", "40137": "BanCoppel",
    "40166": "Banco del Bienestar", "90638": "Nu", "90646": "STP", "90722": "Mercado Pago",
}

SOURCES = ("webhook", "recovery", "simulation")


def payer_from(metadata: dict) -> tuple[str | None, str | None, str | None]:
    """(banco, últimos 4 de la CLABE, clave de rastreo) de quien pagó. Nunca guardamos la CLABE completa."""
    if not isinstance(metadata, dict):
        return None, None, None
    clabe = re.sub(r"\D", "", str(metadata.get("clabe") or ""))
    code = re.sub(r"\D", "", str(metadata.get("bankCode") or ""))
    bank = BANKS.get(code) or (BANKS.get("40" + clabe[:3]) if len(clabe) >= 3 else None)
    tracking = str(metadata.get("trackingKey") or "").strip() or None
    return bank, (clabe[-4:] if len(clabe) >= 4 else None), tracking


def _mismatch(amount: float, expected: float | None) -> bool:
    return expected is not None and abs(expected - amount) > 0.001


def payment_to_dict(r: sqlite3.Row) -> dict:
    return {
        "amountWords": amount_letters(r["amount"]),
        "transactionId": r["transaction_id"],
        "codiQrId": r["codi_qr_id"],
        "kind": r["kind"],
        "amount": r["amount"],
        "expectedAmount": r["expected_amount"],
        "amountMismatch": _mismatch(r["amount"], r["expected_amount"]),
        "concept": r["concept"],
        "paidAt": r["paid_at"],
        "createdAt": r["created_at"],
        "receivedAt": r["received_at"],
        "source": r["source"],
        "recovered": r["source"] == "recovery",
        "simulated": bool(r["simulated"]),
        "phone4": r["phone4"],
        "duplicateSale": bool(r["duplicate_sale"]),
        "payerBank": r["payer_bank"],
        "payerClabe4": r["payer_clabe4"],
        "trackingKey": r["tracking_key"],
    }


def push_to_dict(r: sqlite3.Row) -> dict:
    now = timeutil.now_ts()
    expires_at = r["created_at"] + r["expiration"]
    return {
        "id": r["id"], "kind": "push", "amount": r["amount"], "concept": r["concept"],
        "phone": r["phone"], "phone4": (r["phone"] or "")[-4:], "saleId": r["sale_id"] or r["id"],
        "createdAt": r["created_at"], "expiresAt": expires_at,
        "status": "pending" if now < expires_at else "expired",
    }


def today_summary(limit: int = 50, days: int = 1) -> dict:
    """Pagos desde hace `days` días (1 = solo hoy). Los totales siempre son de hoy y sin simulaciones.
    'Hoy' empieza a medianoche en la zona del negocio (BUSINESS_TZ), no la del servidor."""
    today = timeutil.start_of_day()
    yesterday_start = timeutil.start_of_day(1)
    since = timeutil.start_of_day(max(1, days) - 1)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE paid_at >= ? ORDER BY paid_at DESC, rowid DESC LIMIT ?", (since, limit)
        ).fetchall()
        total, count = conn.execute(
            "SELECT COALESCE(SUM(amount),0), COUNT(*) FROM payments WHERE paid_at >= ? AND simulated = 0",
            (today,),
        ).fetchone()
        yesterday = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE paid_at >= ? AND paid_at < ? AND simulated = 0",
            (yesterday_start, today),
        ).fetchone()[0]
        # Cobros al celular sin pagar de las últimas 24 h (los vencidos siguen visibles para reenviar)
        pend = conn.execute(
            "SELECT * FROM charges WHERE kind='push' AND status='pending' AND created_at >= ? ORDER BY created_at DESC",
            (timeutil.now_ts() - 86400,),
        ).fetchall()
    return {
        "payments": [payment_to_dict(r) for r in rows],
        "pending": [push_to_dict(r) for r in pend],
        "todayTotal": round(total, 2), "todayCount": count, "yesterdayTotal": round(yesterday, 2),
    }


def last_payment():
    with connect() as conn:
        return conn.execute("SELECT * FROM payments ORDER BY paid_at DESC, rowid DESC LIMIT 1").fetchone()


def _find_charge(conn: sqlite3.Connection, payload: dict, qr_id: str, amount: float):
    row = conn.execute("SELECT * FROM charges WHERE id = ?", (qr_id,)).fetchone()
    if not row and payload.get("type") == "codi.pn.payment_received":
        # Respaldo por si el transactionId del aviso no fuera el mismo que nos dio pey al crear la solicitud:
        # el cobro al celular pendiente más reciente con ese monto.
        row = conn.execute(
            "SELECT * FROM charges WHERE kind='push' AND status='pending' AND ABS(amount - ?) < 0.001"
            " AND created_at >= ? ORDER BY created_at DESC LIMIT 1",
            (amount, timeutil.now_ts() - 86400),
        ).fetchone()
    return row


async def record_payment(payload: dict, *, source: str = "webhook") -> dict:
    """Guarda un pago de pey una sola vez (clave: transactionId) y avisa a las pantallas.

    - Se anuncia en voz solo si es nuevo y se pagó hace menos de ANNOUNCE_WINDOW_SECONDS.
      Los más viejos (respaldo que llega tarde, webhook reintentado) entran callados al historial.
    - Si ya existía (p. ej. el respaldo lo trajo antes que el webhook), no se repite: solo se anota
      `received_at` cuando por fin llega el webhook.
    """
    assert source in SOURCES
    simulated = source == "simulation"
    now = timeutil.now_ts()
    tx_id = str(payload["transactionId"])
    # QR: se liga por codiQrId. Cobro al celular: no trae codiQrId, se liga por transactionId (el id que guardamos).
    qr_id = payload.get("codiQrId") or tx_id
    amount = round(float(payload.get("amount") or 0), 2)
    paid_at = timeutil.to_seconds(payload.get("datePaid")) or now
    received_at = now if source == "webhook" else None

    with connect() as conn:
        row = _find_charge(conn, payload, qr_id, amount)
        if row:
            qr_id = row["id"]
        kind = row["kind"] if row else "external"
        charge_has_amount = bool(row) and kind in ("amount", "push")
        expected = row["amount"] if charge_has_amount else None
        # Preferimos el concepto que guardamos nosotros (el webhook puede traer "Negocio · concepto")
        concept = row["concept"] if row else (payload.get("concept") or payload.get("description") or "")
        phone4 = (row["phone"] or "")[-4:] if row and kind == "push" else None
        payer_bank, payer_clabe4, tracking_key = payer_from(payload.get("metadata") or {})
        # ¿Esta venta ya estaba pagada? (p. ej. pagó el QR de respaldo y también la solicitud al celular)
        sale_id = (row["sale_id"] or row["id"]) if charge_has_amount else None
        dup_sale = bool(sale_id) and conn.execute(
            "SELECT 1 FROM payments p JOIN charges c ON c.id = p.codi_qr_id"
            " WHERE COALESCE(c.sale_id, c.id) = ? AND p.transaction_id != ? LIMIT 1", (sale_id, tx_id),
        ).fetchone() is not None
        inserted = conn.execute(
            "INSERT OR IGNORE INTO payments (transaction_id, codi_qr_id, kind, amount, expected_amount, concept,"
            " paid_at, created_at, received_at, source, simulated, phone4, duplicate_sale, payer_bank, payer_clabe4,"
            " tracking_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tx_id, qr_id, kind, amount, expected, concept, paid_at, now, received_at, source, int(simulated),
             phone4, int(dup_sale), payer_bank, payer_clabe4, tracking_key),
        ).rowcount == 1
        if not inserted:
            if received_at:
                conn.execute("UPDATE payments SET received_at=? WHERE transaction_id=? AND received_at IS NULL",
                             (received_at, tx_id))
            stored = conn.execute("SELECT * FROM payments WHERE transaction_id=?", (tx_id,)).fetchone()
            return {**payment_to_dict(stored), "type": "payment", "duplicate": True, "announced": False}
        if charge_has_amount and row["status"] != "paid":
            conn.execute(
                "UPDATE charges SET status='paid', paid_at=?, paid_amount=?, transaction_id=?, simulated=? WHERE id=?",
                (paid_at, amount, tx_id, int(simulated), qr_id),
            )

    announce = now - paid_at <= config.ANNOUNCE_WINDOW_SECONDS
    event = {
        "type": "payment" if announce else "history",  # 'history': solo refresca la lista, sin voz
        "announced": announce,
        "verified": not simulated,
        "simulated": simulated,
        "duplicate": False,
        "source": source,
        "recovered": source == "recovery",
        "chargeId": qr_id,
        "kind": kind,  # fixed | amount | push | external
        "phone4": phone4,
        "duplicateSale": dup_sale,
        "payerBank": payer_bank,
        "payerClabe4": payer_clabe4,
        "trackingKey": tracking_key,
        "amount": amount,
        "amountWords": amount_letters(amount),
        "expectedAmount": expected,
        "amountMismatch": _mismatch(amount, expected),
        "concept": concept,
        "transactionId": tx_id,
        "datePaid": paid_at,
        "speech": speech_for_amount(amount, simulated),
    }
    await bus.publish(event)
    log.info("PAGO %s %s (%s%s): $%.2f qr=%s tx=%s", kind, "SIMULADO" if simulated else "VERIFICADO", source,
             "" if announce else ", sin anunciar", amount, qr_id, tx_id)
    return event
