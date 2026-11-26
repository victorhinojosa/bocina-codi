"""Cuenta: registro, entrar/salir, quién soy y vincular la bocina del mostrador."""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import auth, config, merchants, pey, timeutil
from app.auth import Viewer
from app.db import connect
from app.routes.links import links_enabled

log = logging.getLogger("bocina")
router = APIRouter()

PAIR_TTL = 10 * 60


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _clean_name(s: str) -> str:
    return " ".join((s or "").split())[:80]


# --- registro ------------------------------------------------------------------
class SignupIn(BaseModel):
    phone: str = Field(max_length=20)
    pin: str = Field(max_length=6)
    firstName: str = Field(max_length=80)
    lastName: str = Field(max_length=80)
    businessName: str = Field(max_length=60)
    clabe: str = Field(max_length=24)


@router.post("/api/auth/signup")
async def signup(body: SignupIn, request: Request, response: Response) -> dict:
    phone = pey.clean_phone(body.phone)
    if not phone:
        raise _err(422, "bad_phone", "El celular debe tener 10 dígitos.")
    if problem := auth.weak_pin(body.pin):
        raise _err(422, "bad_pin", problem)
    first, last, biz = _clean_name(body.firstName), _clean_name(body.lastName), _clean_name(body.businessName)
    if not first or not last:
        raise _err(422, "bad_name", "Escribe tu nombre y apellidos como aparecen en tu banco.")
    if len(biz) < 2:
        raise _err(422, "bad_business", "Escribe el nombre de tu negocio.")
    clabe = "".join(ch for ch in body.clabe if ch.isdigit())
    if problem := merchants.clabe_problem(clabe):
        raise _err(422, "bad_clabe", problem)
    with connect() as conn:
        if conn.execute("SELECT 1 FROM users WHERE phone=?", (phone,)).fetchone():
            raise _err(409, "phone_taken", "Ese celular ya tiene cuenta. Entra con tu PIN.")
        if conn.execute("SELECT 1 FROM merchants WHERE clabe=?", (clabe,)).fetchone():
            raise _err(409, "clabe_taken", "Esa CLABE ya está registrada en otra cuenta.")
    if not auth.signup_allowed(auth.client_ip(request)):
        raise _err(429, "too_many", "Demasiados registros desde esta conexión. Intenta en una hora.")

    # pey da de alta la CLABE; si la rechaza no creamos nada
    account = await pey.register_bank_account(alias=biz, name=f"{first} {last}", clabe=clabe)
    try:
        uid, mid = merchants.create(phone=phone, pin=body.pin, first_name=first, last_name=last,
                                    business_name=biz, clabe=clabe, bank_account=account)
    except Exception:  # p. ej. dos registros simultáneos con el mismo celular
        raise _err(409, "phone_taken", "Ese celular ya tiene cuenta. Entra con tu PIN.")
    log.info("Negocio nuevo: %s (cuenta pey %s, %s)", biz, account.get("id"), account.get("codiStatus"))
    auth.start_session(response, request, uid)
    return {"ok": True}


# --- entrar / salir ------------------------------------------------------------
class LoginIn(BaseModel):
    phone: str = Field(max_length=20)
    pin: str = Field(max_length=12)


@router.post("/api/auth/login")
async def login(body: LoginIn, request: Request, response: Response) -> dict:
    phone, ip = pey.clean_phone(body.phone) or body.phone, auth.client_ip(request)
    if auth.login_locked(phone, ip):
        raise _err(429, "locked", "Demasiados intentos. Espera 15 minutos e intenta de nuevo.")
    with connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
    if not user or not auth.check_pin(body.pin, user["pin_hash"]):
        auth.record_failure(phone, ip)
        raise _err(401, "bad_login", "Celular o PIN incorrecto.")
    auth.clear_failures(phone)
    auth.start_session(response, request, user["id"])
    return {"ok": True}


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict:
    auth.end_session(response, request)
    return {"ok": True}


# --- quién soy -----------------------------------------------------------------
def demo_push_left(v: Viewer) -> dict | None:
    if not v.is_demo:
        return None
    day = timeutil.start_of_day()
    with connect() as conn:
        mine = conn.execute("SELECT COUNT(*) FROM push_sends WHERE session_hash=?", (v.session_hash,)).fetchone()[0]
        today = conn.execute("SELECT COUNT(*) FROM push_sends WHERE merchant_id=? AND at>=?", (v.merchant_id, day)).fetchone()[0]
    return {"session": max(0, config.DEMO_PUSH_PER_SESSION - mine), "today": max(0, config.DEMO_PUSH_PER_DAY - today),
            "maxAmount": config.DEMO_PUSH_MAX_AMOUNT}


@router.get("/api/me")
async def me(v: Viewer = Depends(auth.viewer)) -> dict:
    m = await merchants.refresh_status(v.merchant)  # mientras se activa, consulta a pey como respaldo del webhook
    out = {"merchant": {**merchants.merchant_dict(m), "linksEnabled": links_enabled(m)},
           "store": {"id": v.store_id, "name": v.store["name"]}, "device": v.is_device}
    if not v.is_device:
        out.update(user={"firstName": v.user["first_name"], "lastName": v.user["last_name"], "phone4": v.user["phone"][-4:]},
                   role=v.role, demoPush=demo_push_left(v))
    return out


# --- corregir la CLABE si pey la rechazó -----------------------------------------
class BankIn(BaseModel):
    firstName: str = Field(max_length=80)
    lastName: str = Field(max_length=80)
    clabe: str = Field(max_length=24)


@router.post("/api/account/bank")
async def resubmit_bank(body: BankIn, v: Viewer = Depends(auth.owner)) -> dict:
    auth.forbid_demo(v, "Cambiar la CLABE")
    if v.merchant["codi_status"] not in ("ERROR",):
        raise _err(409, "not_needed", "Tu cuenta ya está en proceso de activación.")
    first, last = _clean_name(body.firstName), _clean_name(body.lastName)
    clabe = "".join(ch for ch in body.clabe if ch.isdigit())
    if not first or not last:
        raise _err(422, "bad_name", "Escribe tu nombre y apellidos como aparecen en tu banco.")
    if problem := merchants.clabe_problem(clabe):
        raise _err(422, "bad_clabe", problem)
    account = await pey.register_bank_account(alias=v.merchant["business_name"], name=f"{first} {last}", clabe=clabe)
    with connect() as conn:
        conn.execute(
            "UPDATE merchants SET legal_name=?, clabe=?, bank_name=?, deposit_label=?, pey_bank_account_id=?, codi_status=?,"
            " codi_error=NULL, codi_checked_at=? WHERE id=?",
            (f"{first} {last}", clabe, merchants.bank_for_clabe(clabe), merchants.deposit_label(clabe), account["id"],
             account.get("codiStatus") or "PENDING", timeutil.now_ts(), v.merchant_id),
        )
        conn.execute("UPDATE users SET first_name=?, last_name=? WHERE id=?", (first, last, v.user["id"]))
    return {"ok": True}


# --- vincular la bocina ----------------------------------------------------------
@router.post("/api/devices/pair")
async def pair_request(request: Request, response: Response) -> dict:
    """La bocina pide un código de 6 dígitos y lo muestra; el dueño lo escribe en su App."""
    with connect() as conn:
        conn.execute("DELETE FROM pair_codes WHERE expires_at < ?", (timeutil.now_ts(),))
        for _ in range(20):
            code = f"{secrets.randbelow(1_000_000):06d}"
            if not conn.execute("SELECT 1 FROM pair_codes WHERE code=?", (code,)).fetchone():
                break
        poll = auth.new_token()
        expires = timeutil.now_ts() + PAIR_TTL
        conn.execute("INSERT INTO pair_codes (code, poll_hash, expires_at) VALUES (?, ?, ?)", (code, auth.token_hash(poll), expires))
    auth.set_cookie(response, request, auth.PAIR_COOKIE, poll, PAIR_TTL)
    return {"code": code, "expiresAt": expires}


@router.get("/api/devices/pair")
async def pair_status(request: Request, response: Response) -> dict:
    """La bocina pregunta cada pocos segundos si ya la vincularon; la primera vez que sí, recibe su cookie."""
    poll = request.cookies.get(auth.PAIR_COOKIE)
    if not poll:
        raise _err(410, "expired", "El código venció.")
    with connect() as conn:
        row = conn.execute("SELECT * FROM pair_codes WHERE poll_hash=?", (auth.token_hash(poll),)).fetchone()
        if not row or row["expires_at"] < timeutil.now_ts():
            raise _err(410, "expired", "El código venció.")
        if not row["device_token"]:
            return {"paired": False, "code": row["code"], "expiresAt": row["expires_at"]}
        conn.execute("DELETE FROM pair_codes WHERE code=?", (row["code"],))
    auth.set_cookie(response, request, auth.DEVICE_COOKIE, row["device_token"], 5 * 365 * 86400)
    response.delete_cookie(auth.PAIR_COOKIE, path="/")
    return {"paired": True}


class ClaimIn(BaseModel):
    code: str = Field(max_length=12)


@router.post("/api/devices/claim")
async def pair_claim(body: ClaimIn, v: Viewer = Depends(auth.owner)) -> dict:
    code = "".join(ch for ch in body.code if ch.isdigit())
    token = auth.new_token()
    with connect() as conn:
        row = conn.execute("SELECT * FROM pair_codes WHERE code=? AND expires_at>=? AND device_token IS NULL",
                           (code, timeutil.now_ts())).fetchone()
        if not row:
            raise _err(404, "bad_code", "Ese código no existe o ya venció. Revisa el que muestra la bocina.")
        conn.execute("UPDATE pair_codes SET store_id=?, device_token=? WHERE code=?", (v.store_id, token, code))
        conn.execute("INSERT INTO devices (token_hash, store_id, created_at) VALUES (?, ?, ?)",
                     (auth.token_hash(token), v.store_id, timeutil.now_ts()))
    log.info("Bocina vinculada a %s", v.store["name"])
    return {"ok": True}


@router.post("/api/devices/forget")
async def forget_device(request: Request, response: Response) -> dict:
    """La bocina se desvincula a sí misma (botón en la bocina)."""
    token = request.cookies.get(auth.DEVICE_COOKIE)
    if token:
        with connect() as conn:
            conn.execute("DELETE FROM devices WHERE token_hash=?", (auth.token_hash(token),))
    response.delete_cookie(auth.DEVICE_COOKIE, path="/")
    return {"ok": True}
