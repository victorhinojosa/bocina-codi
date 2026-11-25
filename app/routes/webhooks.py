"""Webhook de pey: LA fuente de verdad del pago (con firma Standard Webhooks)."""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from standardwebhooks.webhooks import Webhook

from app import config, timeutil
from app.db import connect
from app.payments import record_payment

log = logging.getLogger("bocina")
router = APIRouter()

PAYMENT_EVENTS = ("codi.qr.payment_received", "codi.pn.payment_received")


@router.post("/", include_in_schema=False)  # por si la URL del webhook quedó sin /webhooks/pey
@router.post("/webhooks/pey")
async def pey_webhook(request: Request) -> JSONResponse:
    raw = (await request.body()).decode("utf-8")
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not config.PEY_WEBHOOK_SECRET:
        log.error("Llegó un webhook pero falta PEY_WEBHOOK_SECRET; no se puede verificar")
        return JSONResponse({"error": "webhook secret not configured"}, status_code=503)

    # 1) Firma sobre el cuerpo crudo
    try:
        Webhook(config.PEY_WEBHOOK_SECRET).verify(raw, headers)
    except Exception as e:
        log.warning("Webhook rechazado (firma inválida): %s", e)
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    try:
        payload = json.loads(raw)
    except ValueError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    webhook_id = headers["webhook-id"]  # la verificación de firma exige este header
    event_type = payload.get("type", "")

    # 2) ¿Ya lo procesamos? (pey reintenta el mismo webhook-id)
    with connect() as conn:
        if conn.execute("SELECT 1 FROM webhook_events WHERE webhook_id=?", (webhook_id,)).fetchone():
            return JSONResponse({"ok": True, "duplicate": True})

    # 3) Procesar. Si algo falla respondemos 500 y NO lo marcamos como visto: pey reintenta y no se pierde.
    #    Procesarlo dos veces es seguro: el pago se guarda una sola vez por transactionId.
    if event_type in PAYMENT_EVENTS:
        if not payload.get("transactionId"):
            payload["transactionId"] = f"wh-{webhook_id}"
        await record_payment(payload, source="webhook")
    else:
        log.info("Webhook %s recibido (sin manejador): %s", event_type, raw[:300])

    # 4) Marcarlo como visto solo después de procesarlo bien
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO webhook_events (webhook_id, received_at, type, payload) VALUES (?, ?, ?, ?)",
            (webhook_id, timeutil.now_ts(), event_type, raw),
        )
    return JSONResponse({"ok": True})
