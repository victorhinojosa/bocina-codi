"""Link de pago: una página de pey (tarjeta o CoDi) que el negocio manda por WhatsApp a quien no está enfrente.

pey no deja elegir la cuenta de depósito del link (no hay bankAccountId), así que el dinero cae en la cuenta
de la API key. Por eso solo lo pueden usar los negocios que cobran en esa cuenta (la demo); a un negocio con
CLABE propia nunca le cobramos en nuestra cuenta.
"""

import html
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app import auth, config, pey, timeutil
from app.auth import Viewer
from app.db import connect
from app.events import bus
from app.payments import link_to_dict
from app.routes.charges import _clean_concept, _require_active

log = logging.getLogger("bocina")
router = APIRouter()


def links_enabled(merchant) -> bool:
    return not merchant["pey_bank_account_id"] and bool(merchant["is_demo"])


def public_base(request: Request) -> str:
    """URL pública del servidor (pey exige HTTPS para las páginas de regreso). PUBLIC_URL la fija; si no,
    se toma del proxy de Railway."""
    if config.PUBLIC_URL:
        return config.PUBLIC_URL.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


class LinkIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    concept: str = Field(default="", max_length=100)
    saleId: str | None = Field(default=None, max_length=64)


@router.post("/api/links")
async def create_link(body: LinkIn, request: Request, v: Viewer = Depends(auth.owner)) -> dict:
    _require_active(v)
    if not links_enabled(v.merchant):
        raise pey.PeyError(409, "link_unavailable",
                           "El link de pago todavía no puede depositar a tu propia CLABE. Usa el QR o el cobro al celular.")
    base = public_base(request)
    if not base.startswith("https://"):
        raise pey.PeyError(409, "needs_https", "El link de pago necesita una dirección HTTPS (funciona en Railway, no en localhost).")
    amount = round(body.amount, 2)
    concept, _ = _clean_concept(v, body.concept)
    ref = body.saleId or f"din-{auth.new_id()}"
    data = await pey.create_payment_link(amount, f"{base}/pago/listo", f"{base}/pago/cancelado", ref,
                                         {"source": "din", "merchant": v.merchant_id, "concept": concept[:100]})
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, link_url,"
            " sale_id, merchant_id, store_id) VALUES (?, ?, ?, ?, 'pending', ?, 0, 'link', ?, ?, ?, ?)",
            (data["id"], amount, concept, ref, timeutil.now_ts(), data["url"], body.saleId or data["id"], v.merchant_id, v.store_id),
        )
        row = conn.execute("SELECT * FROM charges WHERE id=?", (data["id"],)).fetchone()
    log.info("Link de pago %s por $%.2f", data["id"], amount)
    await bus.publish({"type": "pending"}, v.merchant_id)
    return {**link_to_dict(row), "businessName": v.merchant["business_name"]}


@router.post("/api/links/{link_id}/dismiss")
async def dismiss_link(link_id: str, v: Viewer = Depends(auth.owner)) -> dict:
    with connect() as conn:
        conn.execute("UPDATE charges SET status='dismissed' WHERE id=? AND merchant_id=? AND kind='link' AND status='pending'",
                     (link_id, v.merchant_id))
    await bus.publish({"type": "pending"}, v.merchant_id)
    return {"ok": True}


# --- páginas a las que pey regresa al cliente ------------------------------------------
PAGE = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="/static/icon.svg" type="image/svg+xml"><link rel="stylesheet" href="/static/tokens.css"><title>Din</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font-family:var(--font-sans);text-align:center;padding:24px}}
.c{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-xl);padding:32px 26px;max-width:360px}}
.i{{width:64px;height:64px;border-radius:50%;display:grid;place-items:center;margin:0 auto 14px;font-size:30px;color:var(--on-brand);background:{color}}}
h1{{font-size:24px;margin:0 0 8px;letter-spacing:-.5px}}p{{color:var(--ink-muted);line-height:1.5;margin:0}}
.d{{display:flex;align-items:center;justify-content:center;gap:6px;font-weight:800;font-size:20px;margin-top:22px}}.d img{{width:20px}}</style></head>
<body><div class="c"><div class="i">{icon}</div><h1>{title}</h1><p>{text}</p><div class="d"><img src="/static/logo-din.svg" alt="">Din</div></div></body></html>"""


@router.get("/pago/listo", include_in_schema=False)
async def link_paid() -> HTMLResponse:
    return HTMLResponse(PAGE.format(color="var(--success)", icon="✓", title="¡Gracias por tu pago!",
                                    text=html.escape("El negocio ya recibió el aviso. Puedes cerrar esta página.")))


@router.get("/pago/cancelado", include_in_schema=False)
async def link_back() -> HTMLResponse:
    return HTMLResponse(PAGE.format(color="var(--ink-muted)", icon="←", title="No se hizo el pago",
                                    text=html.escape("Puedes volver a abrir el link que te mandaron cuando quieras pagar.")))
