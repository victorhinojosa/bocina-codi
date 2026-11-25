"""Entrar con celular + PIN de 6 dígitos, sesiones con cookie y quién está viendo (persona o bocina).

- El PIN se guarda con scrypt; las sesiones y bocinas se guardan como sha256 del token de su cookie.
- 5 PIN equivocados bloquean ese celular 15 minutos (y 20 por IP), así adivinar 1,000,000 no es práctico.
- Una pantalla puede verse con sesión de persona (la App, o la bocina en la misma compu) o con
  token de bocina vinculada (la bocina del mostrador, sin usuario).
"""

import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

from app import config, timeutil
from app.db import connect

SESSION_COOKIE = "din_session"
DEVICE_COOKIE = "din_device"
PAIR_COOKIE = "din_pair"

MAX_PHONE_FAILS = 5
MAX_IP_FAILS = 20
LOCK_SECONDS = 15 * 60
MAX_SIGNUPS_PER_IP_HOUR = 5


# --- PIN ----------------------------------------------------------------------
def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_pin(pin: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False


def weak_pin(pin: str) -> str | None:
    """Motivo si el PIN es inválido o demasiado fácil; None si está bien."""
    if not re.fullmatch(r"\d{6}", pin or ""):
        return "El PIN debe tener 6 dígitos."
    if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
        return "Ese PIN es muy fácil de adivinar. Elige otro."
    return None


# --- tokens -------------------------------------------------------------------
def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_id() -> str:
    return secrets.token_hex(8)


def _secure(request: Request) -> bool:
    # Railway termina TLS en su proxy y nos llega http con X-Forwarded-Proto: https
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").startswith("https")


def set_cookie(response: Response, request: Request, name: str, value: str, max_age: int) -> None:
    response.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax", secure=_secure(request), path="/")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else "?")


# --- intentos (fuerza bruta) --------------------------------------------------
def _recent(conn: sqlite3.Connection, key: str, window: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM login_attempts WHERE key=? AND at>=?",
                        (key, timeutil.now_ts() - window)).fetchone()[0]


def login_locked(phone: str, ip: str) -> bool:
    with connect() as conn:
        return (_recent(conn, f"phone:{phone}", LOCK_SECONDS) >= MAX_PHONE_FAILS
                or _recent(conn, f"ip:{ip}", LOCK_SECONDS) >= MAX_IP_FAILS)


def record_failure(phone: str, ip: str) -> None:
    now = timeutil.now_ts()
    with connect() as conn:
        conn.executemany("INSERT INTO login_attempts (key, at) VALUES (?, ?)", [(f"phone:{phone}", now), (f"ip:{ip}", now)])
        conn.execute("DELETE FROM login_attempts WHERE at < ?", (now - 86400,))


def clear_failures(phone: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM login_attempts WHERE key=?", (f"phone:{phone}",))


def signup_allowed(ip: str) -> bool:
    with connect() as conn:
        if _recent(conn, f"signup:{ip}", 3600) >= MAX_SIGNUPS_PER_IP_HOUR:
            return False
        conn.execute("INSERT INTO login_attempts (key, at) VALUES (?, ?)", (f"signup:{ip}", timeutil.now_ts()))
        return True


# --- sesiones -----------------------------------------------------------------
def start_session(response: Response, request: Request, user_id: str) -> str:
    token = new_token()
    now = timeutil.now_ts()
    max_age = config.SESSION_DAYS * 86400
    with connect() as conn:
        conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                     (token_hash(token), user_id, now, now + max_age))
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    set_cookie(response, request, SESSION_COOKIE, token, max_age)
    return token


def end_session(response: Response, request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
    response.delete_cookie(SESSION_COOKIE, path="/")


# --- quién está viendo --------------------------------------------------------
@dataclass
class Viewer:
    merchant: sqlite3.Row
    store: sqlite3.Row
    user: sqlite3.Row | None = None   # None = bocina vinculada
    role: str | None = None
    session_hash: str | None = None

    @property
    def merchant_id(self) -> str:
        return self.merchant["id"]

    @property
    def store_id(self) -> str:
        return self.store["id"]

    @property
    def is_demo(self) -> bool:
        return bool(self.merchant["is_demo"])

    @property
    def is_device(self) -> bool:
        return self.user is None


def _first_store(conn: sqlite3.Connection, merchant_id: str):
    return conn.execute("SELECT * FROM stores WHERE merchant_id=? ORDER BY created_at LIMIT 1", (merchant_id,)).fetchone()


def _from_session(conn: sqlite3.Connection, token: str) -> Viewer | None:
    h = token_hash(token)
    row = conn.execute(
        "SELECT u.*, m.merchant_id, m.role FROM sessions s JOIN users u ON u.id = s.user_id"
        " JOIN memberships m ON m.user_id = u.id WHERE s.token_hash=? AND s.expires_at>?",
        (h, timeutil.now_ts()),
    ).fetchone()
    if not row:
        return None
    merchant = conn.execute("SELECT * FROM merchants WHERE id=?", (row["merchant_id"],)).fetchone()
    store = _first_store(conn, row["merchant_id"])
    if not merchant or not store:
        return None
    return Viewer(merchant=merchant, store=store, user=row, role=row["role"], session_hash=h)


def _from_device(conn: sqlite3.Connection, token: str) -> Viewer | None:
    h = token_hash(token)
    store = conn.execute("SELECT s.* FROM devices d JOIN stores s ON s.id = d.store_id WHERE d.token_hash=?", (h,)).fetchone()
    if not store:
        return None
    conn.execute("UPDATE devices SET last_seen=? WHERE token_hash=?", (timeutil.now_ts(), h))
    merchant = conn.execute("SELECT * FROM merchants WHERE id=?", (store["merchant_id"],)).fetchone()
    return Viewer(merchant=merchant, store=store) if merchant else None


def current_viewer(request: Request) -> Viewer | None:
    with connect() as conn:
        token = request.cookies.get(SESSION_COOKIE)
        if token and (v := _from_session(conn, token)):
            return v
        token = request.cookies.get(DEVICE_COOKIE)
        if token and (v := _from_device(conn, token)):
            return v
    return None


# Dependencias de FastAPI
def viewer(request: Request) -> Viewer:
    """Persona con sesión o bocina vinculada."""
    v = current_viewer(request)
    if not v:
        raise HTTPException(401, {"code": "auth", "message": "Inicia sesión"})
    return v


def owner(request: Request) -> Viewer:
    """Dueño del negocio con sesión (las bocinas no pueden cobrar ni ver el historial completo)."""
    v = viewer(request)
    if v.is_device or v.role != "owner":
        raise HTTPException(403, {"code": "forbidden", "message": "Solo el dueño puede hacer esto"})
    return v


def forbid_demo(v: Viewer, what: str = "Esto") -> None:
    if v.is_demo:
        raise HTTPException(403, {"code": "demo_locked", "message": f"{what} está bloqueado en la cuenta demo."})
