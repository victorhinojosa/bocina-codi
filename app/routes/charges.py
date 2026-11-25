"""Cobrar: QR fijo, QR con monto, cobro al celular y simulación."""

import logging
import random
import time

import segno
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import auth, config, pey, timeutil
from app.auth import Viewer
from app.db import connect, fixed_row
from app.events import bus
from app.payments import push_to_dict, record_payment

log = logging.getLogger("bocina")
router = APIRouter()


def qr_svg(qr_string: str) -> str:
    # omitsize=True -> el SVG lleva viewBox y escala completo (sin esto el CSS lo recortaba).
    # border=4 es la zona blanca estándar que piden los lectores de QR.
    return segno.make(qr_string, error="m").svg_inline(
        scale=6, border=4, dark="#000000", light="#ffffff", omitsize=True
    )


# --- QR fijo (el de la tiendita) -------------------------------------------
class FixedIn(BaseModel):
    name: str = Field(default="", max_length=100)


def _fixed_dict(row) -> dict:
    return {"id": row["id"], "name": row["concept"], "createdAt": row["created_at"], "qrSvg": qr_svg(row["qr_string"])}


def _require_active(v: Viewer) -> None:
    """Sin cuenta activa en CoDi no se cobra: el dinero caería en la cuenta de la API key, no en la del negocio."""
    if v.merchant["codi_status"] != "ACTIVE" or (not v.merchant["pey_bank_account_id"] and not v.is_demo):
        raise pey.PeyError(409, "not_active", "Tu cuenta se está activando en CoDi. Podrás cobrar en cuanto esté lista.")


@router.get("/api/fixed-qr")
async def get_fixed_qr(v: Viewer = Depends(auth.viewer)) -> dict:
    row = fixed_row(v.store_id)
    return {"fixed": _fixed_dict(row) if row and row["qr_string"] else None}


@router.post("/api/fixed-qr")
async def create_fixed_qr(body: FixedIn, v: Viewer = Depends(auth.owner)) -> dict:
    """Crea un QR fijo nuevo (y retira el anterior de la pantalla).
    Ojo: un QR fijo viejo que ya imprimiste sigue funcionando y sus pagos siguen llegando."""
    auth.forbid_demo(v, "Cambiar el QR fijo")
    _require_active(v)
    name = (body.name or v.merchant["business_name"]).strip() or v.merchant["business_name"]
    qr_id, qr_string, num_ref = await pey.create_qr(0, name, 0, v.merchant["pey_bank_account_id"])
    now = timeutil.now_ts()
    with connect() as conn:
        conn.execute("UPDATE charges SET status='retired' WHERE kind='fixed' AND status='active' AND store_id=?", (v.store_id,))
        conn.execute(
            "INSERT OR REPLACE INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, qr_string,"
            " merchant_id, store_id) VALUES (?, 0, ?, ?, 'active', ?, 0, 'fixed', ?, ?, ?)",
            (qr_id, name, num_ref, now, qr_string, v.merchant_id, v.store_id),
        )
    log.info("QR fijo creado %s (%s)", qr_id, name)
    await bus.publish({"type": "fixed"}, v.merchant_id)  # el mostrador recarga su QR
    return {"fixed": _fixed_dict(fixed_row(v.store_id))}


# --- Cobro con monto y al celular -----------------------------------------
class ChargeIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    concept: str = Field(default="", max_length=100)
    expiration: int | None = Field(default=None, ge=0)
    saleId: str | None = Field(default=None, max_length=64)  # QR de respaldo de un cobro al celular


class PushIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    phone: str = Field(min_length=1, max_length=20)
    concept: str = Field(default="", max_length=100)
    saleId: str | None = Field(default=None, max_length=64)  # al reenviar, la misma venta


def _clean_concept(v: Viewer, concept: str) -> tuple[str, str]:
    """(concepto para la app, concepto que ve el cliente en su banco: 'Negocio · concepto')."""
    concept = concept.strip()
    if concept.lower() == "venta":  # el asistente usa "Venta" cuando no hay concepto
        concept = ""
    fixed = fixed_row(v.store_id)
    biz = (fixed["concept"] if fixed else "") or v.merchant["business_name"]
    return concept, (f"{biz} · {concept}"[:100] if concept else biz)


def _check_demo_push(v: Viewer, amount: float) -> None:
    """En la cuenta demo el cobro al celular manda una solicitud real a un celular real: se limita."""
    if not v.is_demo:
        return
    if amount > config.DEMO_PUSH_MAX_AMOUNT:
        raise pey.PeyError(422, "demo_limit",
                           f"En la cuenta demo el cobro al celular es de máximo ${config.DEMO_PUSH_MAX_AMOUNT:,.0f}.")
    with connect() as conn:
        mine = conn.execute("SELECT COUNT(*) FROM push_sends WHERE session_hash=?", (v.session_hash,)).fetchone()[0]
        today = conn.execute("SELECT COUNT(*) FROM push_sends WHERE merchant_id=? AND at>=?",
                             (v.merchant_id, timeutil.start_of_day())).fetchone()[0]
    if mine >= config.DEMO_PUSH_PER_SESSION:
        raise pey.PeyError(429, "demo_limit",
                           f"Ya enviaste {config.DEMO_PUSH_PER_SESSION} cobros al celular en la demo. Prueba con un QR.")
    if today >= config.DEMO_PUSH_PER_DAY:
        raise pey.PeyError(429, "demo_limit", "La demo llegó al límite de cobros al celular de hoy. Prueba con un QR.")


@router.post("/api/push")
async def create_push(body: PushIn, v: Viewer = Depends(auth.owner)) -> dict:
    """Cobro al celular: pey le manda al cliente una solicitud CoDi a su app del banco."""
    _require_active(v)
    phone = pey.clean_phone(body.phone)
    if not phone:
        raise pey.PeyError(422, "bad_phone", "El número debe tener 10 dígitos.")
    amount = round(body.amount, 2)
    _check_demo_push(v, amount)
    concept, pey_concept = _clean_concept(v, body.concept)
    data = await pey.push(amount, phone, pey_concept, config.PUSH_EXPIRATION, {"source": "bocina-codi"},
                          v.merchant["pey_bank_account_id"])
    tx_id, now = data["transactionId"], timeutil.now_ts()
    with connect() as conn:
        if body.saleId:  # reenvío: el cobro anterior queda reemplazado
            conn.execute("UPDATE charges SET status='replaced' WHERE merchant_id=? AND kind='push' AND status='pending'"
                         " AND sale_id=?", (v.merchant_id, body.saleId))
        conn.execute(
            "INSERT OR REPLACE INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, phone, sale_id,"
            " merchant_id, store_id) VALUES (?, ?, ?, ?, 'pending', ?, ?, 'push', ?, ?, ?, ?)",
            (tx_id, amount, concept, data.get("codiId") or "0", now, config.PUSH_EXPIRATION, phone, body.saleId or tx_id,
             v.merchant_id, v.store_id),
        )
        conn.execute("INSERT INTO push_sends (merchant_id, session_hash, at) VALUES (?, ?, ?)",
                     (v.merchant_id, v.session_hash, now))
        row = conn.execute("SELECT * FROM charges WHERE id=?", (tx_id,)).fetchone()
    log.info("Cobro al celular %s por $%.2f a ···%s", tx_id, amount, phone[-4:])
    await bus.publish({"type": "pending"}, v.merchant_id)
    return push_to_dict(row)


@router.post("/api/push/{charge_id}/dismiss")
async def dismiss_push(charge_id: str, v: Viewer = Depends(auth.owner)) -> dict:
    """Quitar de la lista un cobro al celular que ya no se va a pagar."""
    with connect() as conn:
        conn.execute("UPDATE charges SET status='dismissed' WHERE id=? AND merchant_id=? AND kind='push' AND status='pending'",
                     (charge_id, v.merchant_id))
    await bus.publish({"type": "pending"}, v.merchant_id)
    return {"ok": True}


@router.post("/api/charges")
async def create_charge(body: ChargeIn, v: Viewer = Depends(auth.owner)) -> dict:
    _require_active(v)
    amount = round(body.amount, 2)
    expiration = config.DEFAULT_EXPIRATION if body.expiration is None else body.expiration
    concept, pey_concept = _clean_concept(v, body.concept)
    qr_id, qr_string, num_ref = await pey.create_qr(amount, pey_concept, expiration, v.merchant["pey_bank_account_id"])
    if 0 < expiration < 360:
        expiration = 360
    now = timeutil.now_ts()
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, qr_string, sale_id,"
            " merchant_id, store_id) VALUES (?, ?, ?, ?, 'pending', ?, ?, 'amount', ?, ?, ?, ?)",
            (qr_id, amount, concept, num_ref, now, expiration, qr_string, body.saleId or qr_id, v.merchant_id, v.store_id),
        )
    log.info("Cobro creado %s por $%.2f (%s)", qr_id, amount, concept)
    # El QR con monto se muestra en el celular del dueño (la App); el mostrador solo tiene el QR fijo.
    return {
        "id": qr_id, "amount": amount, "concept": concept, "numRef": num_ref,
        "expiration": expiration, "createdAt": now, "qrSvg": qr_svg(qr_string),
    }


# --- Simulación (solo pruebas; desactivada por defecto) --------------------
@router.post("/api/dev/simulate/{charge_id}")
async def simulate(charge_id: str, amount: float | None = None, v: Viewer = Depends(auth.owner)) -> dict:
    if not config.ALLOW_SIMULATION:
        raise HTTPException(403, "Simulación desactivada (ALLOW_SIMULATION=false)")
    with connect() as conn:
        row = conn.execute("SELECT * FROM charges WHERE id = ? AND merchant_id = ?", (charge_id, v.merchant_id)).fetchone()
    if not row:
        raise HTTPException(404, "QR no encontrado")
    amt = amount if row["kind"] == "fixed" else row["amount"]
    if not amt or amt <= 0:
        amt = round(random.choice([12, 18.5, 25, 37, 85]), 2)
    if row["kind"] == "push":  # el aviso real de pey no trae codiQrId: se liga por transactionId
        return await record_payment(
            {"type": "codi.pn.payment_received", "amount": amt, "concept": row["concept"],
             "datePaid": timeutil.now_ts(), "transactionId": charge_id},
            source="simulation",
        )
    return await record_payment(
        {"type": "codi.qr.payment_received", "codiQrId": charge_id, "amount": amt, "concept": row["concept"],
         "datePaid": timeutil.now_ts(), "transactionId": f"SIM-{time.time_ns()}"},
        source="simulation",
    )
