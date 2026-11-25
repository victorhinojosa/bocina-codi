"""Administración de la plataforma (tú, no los negocios). Protegida con ADMIN_TOKEN; sin él, no existe.

    GET  /api/admin/merchants        negocios registrados, su alta en CoDi y sus pagos
    POST /api/admin/merchants/link   crea una cuenta sobre una CLABE que ya registraste en pey
                                     (no la vuelve a registrar: lee su estado con GET /bank-account/{id})
"""

import hmac
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import auth, config, merchants, pey
from app.db import connect

log = logging.getLogger("bocina")
router = APIRouter()

MAX_ADMIN_FAILS = 10


def require_admin(request: Request) -> None:
    if not config.ADMIN_TOKEN:
        raise HTTPException(404, "Not Found")
    ip = auth.client_ip(request)
    key = f"admin:{ip}"
    with connect() as conn:
        if auth._recent(conn, key, auth.LOCK_SECONDS) >= MAX_ADMIN_FAILS:
            raise HTTPException(429, "Demasiados intentos")
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), config.ADMIN_TOKEN.encode()):
        with connect() as conn:
            conn.execute("INSERT INTO login_attempts (key, at) VALUES (?, strftime('%s','now'))", (key,))
        raise HTTPException(401, "Token incorrecto")


@router.get("/api/admin/merchants", dependencies=[Depends(require_admin)])
async def list_merchants() -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT m.*, u.phone, u.first_name, u.last_name,"
            " (SELECT COUNT(*) FROM payments p WHERE p.merchant_id = m.id AND p.simulated = 0) AS payments,"
            " (SELECT COALESCE(SUM(amount), 0) FROM payments p WHERE p.merchant_id = m.id AND p.simulated = 0) AS total,"
            " (SELECT COUNT(*) FROM devices d JOIN stores s ON s.id = d.store_id WHERE s.merchant_id = m.id) AS speakers"
            " FROM merchants m LEFT JOIN memberships ms ON ms.merchant_id = m.id AND ms.role = 'owner'"
            " LEFT JOIN users u ON u.id = ms.user_id ORDER BY m.created_at DESC"
        ).fetchall()
    return {"merchants": [{
        "businessName": r["business_name"], "owner": f"{r['first_name']} {r['last_name']}", "phone": r["phone"],
        "clabe4": (r["clabe"] or "")[-4:] or None, "bank": r["bank_name"], "peyBankAccountId": r["pey_bank_account_id"],
        "codiStatus": r["codi_status"], "codiError": r["codi_error"], "isDemo": bool(r["is_demo"]),
        "payments": r["payments"], "total": round(r["total"], 2), "speakers": r["speakers"], "createdAt": r["created_at"],
    } for r in rows]}


class LinkIn(BaseModel):
    bankAccountId: str = Field(min_length=1, max_length=64)
    phone: str = Field(max_length=20)
    pin: str = Field(max_length=6)
    firstName: str = Field(max_length=80)
    lastName: str = Field(max_length=80)
    businessName: str = Field(max_length=60)


@router.post("/api/admin/merchants/link", dependencies=[Depends(require_admin)])
async def link_existing(body: LinkIn) -> dict:
    phone = pey.clean_phone(body.phone)
    if not phone:
        raise HTTPException(422, "El celular debe tener 10 dígitos.")
    if problem := auth.weak_pin(body.pin):
        raise HTTPException(422, problem)
    first, last, biz = (" ".join(x.split()) for x in (body.firstName, body.lastName, body.businessName))
    if not first or not last or len(biz) < 2:
        raise HTTPException(422, "Faltan nombre, apellidos o nombre del negocio.")
    try:
        account = await pey.get_bank_account(body.bankAccountId)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, "pey no encontró esa cuenta con nuestra API key (¿se creó con otra API key o en el portal?).")
        raise HTTPException(502, f"pey respondió {e.response.status_code}")
    except httpx.HTTPError as e:
        raise HTTPException(503, f"No se pudo contactar a pey: {e}")
    clabe = account.get("clabe") or ""
    with connect() as conn:
        if conn.execute("SELECT 1 FROM users WHERE phone=?", (phone,)).fetchone():
            raise HTTPException(409, "Ese celular ya tiene cuenta.")
        if conn.execute("SELECT 1 FROM merchants WHERE pey_bank_account_id=? OR (clabe IS NOT NULL AND clabe=?)",
                        (body.bankAccountId, clabe)).fetchone():
            raise HTTPException(409, "Esa cuenta de pey (o su CLABE) ya está ligada a un negocio.")
    _, mid = merchants.create(phone=phone, pin=body.pin, first_name=first, last_name=last, business_name=biz, clabe=clabe,
                              bank_account={"id": body.bankAccountId, "codiStatus": account.get("codiStatus") or "PENDING"})
    if account.get("errorMessage"):
        with connect() as conn:
            conn.execute("UPDATE merchants SET codi_error=? WHERE id=?", (account["errorMessage"], mid))
    if account.get("codiStatus") == "ACTIVE":
        await merchants.ensure_fixed_qr(mid)
    log.info("Admin: cuenta ligada a %s (pey %s, %s)", biz, body.bankAccountId, account.get("codiStatus"))
    return {"ok": True, "businessName": biz, "codiStatus": account.get("codiStatus"), "clabe4": clabe[-4:],
            "holderInPey": account.get("name")}
