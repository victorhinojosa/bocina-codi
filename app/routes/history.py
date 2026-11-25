"""Historial de pagos y eventos en vivo (SSE)."""

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app import payments, timeutil
from app.events import bus
from app.recovery import recovery
from app.speech import money_words

router = APIRouter()


@router.get("/api/last-payment")
async def last_payment() -> dict:
    """Botón 'Último pago' del dispositivo."""
    r = payments.last_payment()
    if not r:
        return {"payment": None, "speech": "Todavía no hay pagos."}
    p = payments.payment_to_dict(r)
    sim = "Simulación. " if p["simulated"] else ""
    return {"payment": p, "speech": f"{sim}Último pago: {money_words(p['amount'])}, {timeutil.spoken_time(p['paidAt'])}."}


@router.get("/api/payments")
async def list_payments(limit: int = 50, days: int = 1) -> dict:
    return payments.today_summary(min(limit, 500), min(days, 90))


@router.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    q = bus.subscribe()
    recovery.kick()  # pantalla nueva o reconectada: buscar pagos que se hayan perdido mientras no estaba

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
                    yield "event: ping\ndata: {}\n\n"  # latido: la página detecta si se cae la conexión
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
