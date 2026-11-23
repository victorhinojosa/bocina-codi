"""
Bocina CoDi — la caja que te dice en voz alta cuando te pagaron.

Dos formas de cobrar con pey/CoDi:
  * QR FIJO   (amount=0, sin expiración): el cliente escanea y pone el monto. Como en las
                tienditas de India. Un solo QR recibe muchos pagos.
  * CON MONTO (amount>0): un QR por cobro, para tickets grandes, pedidos o proveedores.

La confirmación SOLO sale de un webhook de pey con firma válida (Standard Webhooks).
Cada pago se guarda en la tabla `payments` (un QR fijo puede tener cientos).

Asistente de voz: "¿cuánto vendí hoy?", "últimas 3 transacciones", "cóbrale 90".
"""

import asyncio
import hmac
import io
import json
import logging
import os
import random
import re
import sqlite3
import time
from pathlib import Path

import httpx
import segno
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from num2words import num2words
from pydantic import BaseModel, Field
from standardwebhooks.webhooks import Webhook

load_dotenv()


def env(name: str, default: str = "") -> str:
    """Variable de entorno; si está vacía usa el valor por defecto (así `DB_PATH=` en el .env no rompe nada)."""
    v = os.getenv(name, "").strip()
    return v if v else default


# ---------------------------------------------------------------------------
# Config (las llaves viven en el servidor; nunca llegan al navegador)
# ---------------------------------------------------------------------------
PEY_API_KEY = env("PEY_API_KEY", "")
PEY_BASE_URL = env("PEY_BASE_URL", "https://api.pey.mx").rstrip("/")
PEY_WEBHOOK_SECRET = env("PEY_WEBHOOK_SECRET", "")  # whsec_...
DEFAULT_EXPIRATION = int(env("DEFAULT_EXPIRATION", "0"))  # 0 = sin expiración; si se pone, mínimo 360
BUSINESS_NAME = env("BUSINESS_NAME", "Mi tienda")
# Etiqueta de la cuenta donde cae el dinero, solo para mostrar en el perfil (ej. "BBVA ···· 2702"). Opcional.
DEPOSIT_ACCOUNT_LABEL = env("DEPOSIT_ACCOUNT_LABEL", "")
# Cuánto dura una solicitud de cobro al celular (CoDi push). pey exige mínimo 360 s.
PUSH_EXPIRATION = max(360, int(env("PUSH_EXPIRATION", "900")))

ELEVENLABS_API_KEY = env("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = env("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_MODEL = env("ELEVENLABS_MODEL", "eleven_flash_v2_5")

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-haiku-5-5")

ALLOW_SIMULATION = env("ALLOW_SIMULATION", "false").lower() == "true"

# PIN para Ajustes y acciones de administración (vacío = sin PIN, útil en local)
ADMIN_PIN = env("ADMIN_PIN", "")

# QR fijo amarrado a la cuenta: si se definen, el servidor siempre usa este QR (sobrevive reinicios y deploys)
FIXED_QR_ID = env("FIXED_QR_ID", "").strip()
FIXED_QR_STRING = env("FIXED_QR_STRING", "").strip()
FIXED_LOCKED = bool(FIXED_QR_ID and FIXED_QR_STRING)
DB_PATH = env("DB_PATH", str(Path(__file__).resolve().parent.parent / "bocina.db"))
STATIC_DIR = Path(__file__).resolve().parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bocina")

app = FastAPI(title="Bocina CoDi")

# Las páginas se revalidan en cada carga para que nadie vea una versión vieja en caché
NO_CACHE = {"Cache-Control": "no-cache"}


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """Los JS/CSS propios se revalidan (304 si no cambiaron); three.js sí se cachea."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") and not path.startswith("/static/vendor/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)  # p. ej. el volumen /data en Railway
    with db() as conn:
        conn.executescript(
            """
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
                transaction_id TEXT PRIMARY KEY,
                codi_qr_id TEXT,
                kind TEXT,                    -- fixed | amount | push | external
                amount REAL NOT NULL,
                concept TEXT,
                paid_at INTEGER NOT NULL,
                simulated INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS webhook_events (
                webhook_id TEXT PRIMARY KEY,  -- clave de idempotencia (header webhook-id)
                received_at INTEGER NOT NULL,
                type TEXT,
                payload TEXT NOT NULL
            );
            """
        )
        # Migración desde la versión anterior (agrega columnas si faltan)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(charges)")}
        if "kind" not in cols:
            conn.execute("ALTER TABLE charges ADD COLUMN kind TEXT NOT NULL DEFAULT 'amount'")
        if "qr_string" not in cols:
            conn.execute("ALTER TABLE charges ADD COLUMN qr_string TEXT")
        # Cobro al celular: número del cliente y venta a la que pertenece (para detectar pagos dobles)
        if "phone" not in cols:
            conn.execute("ALTER TABLE charges ADD COLUMN phone TEXT")
        if "sale_id" not in cols:
            conn.execute("ALTER TABLE charges ADD COLUMN sale_id TEXT")
        pcols = {r["name"] for r in conn.execute("PRAGMA table_info(payments)")}
        if "phone4" not in pcols:
            conn.execute("ALTER TABLE payments ADD COLUMN phone4 TEXT")
        if "duplicate_sale" not in pcols:
            conn.execute("ALTER TABLE payments ADD COLUMN duplicate_sale INTEGER NOT NULL DEFAULT 0")
        # Quién pagó (del aviso de pey): banco, últimos 4 de su CLABE y clave de rastreo
        for col in ("payer_bank", "payer_clabe4", "tracking_key"):
            if col not in pcols:
                conn.execute(f"ALTER TABLE payments ADD COLUMN {col} TEXT")
        # Pagos viejos -> tabla payments
        conn.execute(
            "INSERT OR IGNORE INTO payments (transaction_id, codi_qr_id, kind, amount, concept, paid_at, simulated)"
            " SELECT transaction_id, id, 'amount', paid_amount, concept, paid_at, simulated FROM charges"
            " WHERE status='paid' AND transaction_id IS NOT NULL"
        )



def seed_fixed_qr() -> None:
    """Si el QR fijo viene en las variables de entorno, lo deja como el QR activo."""
    if not FIXED_LOCKED:
        return
    with db() as conn:
        row = conn.execute("SELECT status FROM charges WHERE id = ?", (FIXED_QR_ID,)).fetchone()
        conn.execute("UPDATE charges SET status='retired' WHERE kind='fixed' AND status='active' AND id != ?", (FIXED_QR_ID,))
        if row:
            conn.execute("UPDATE charges SET status='active', kind='fixed', qr_string=?, concept=? WHERE id=?",
                         (FIXED_QR_STRING, BUSINESS_NAME, FIXED_QR_ID))
        else:
            conn.execute(
                "INSERT INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, qr_string)"
                " VALUES (?, 0, ?, '0', 'active', ?, 0, 'fixed', ?)",
                (FIXED_QR_ID, BUSINESS_NAME, int(time.time()), FIXED_QR_STRING),
            )


init_db()
seed_fixed_qr()


def qr_svg(qr_string: str) -> str:
    # omitsize=True -> el SVG lleva viewBox y escala completo (sin esto el CSS lo recortaba).
    # border=4 es la zona blanca estándar que piden los lectores de QR.
    return segno.make(qr_string, error="m").svg_inline(
        scale=6, border=4, dark="#000000", light="#ffffff", omitsize=True
    )


def start_of_today() -> int:
    t = time.localtime()
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def payment_to_dict(r: sqlite3.Row) -> dict:
    return {
        "amountWords": amount_letters(r["amount"]),
        "transactionId": r["transaction_id"],
        "codiQrId": r["codi_qr_id"],
        "kind": r["kind"],
        "amount": r["amount"],
        "concept": r["concept"],
        "paidAt": r["paid_at"],
        "simulated": bool(r["simulated"]),
        "phone4": r["phone4"],
        "duplicateSale": bool(r["duplicate_sale"]),
        "payerBank": r["payer_bank"],
        "payerClabe4": r["payer_clabe4"],
        "trackingKey": r["tracking_key"],
    }


# Bancos más comunes en SPEI/CoDi (código de 5 dígitos que manda pey y prefijo de 3 dígitos de la CLABE)
BANKS = {
    "40002": "Banamex", "40012": "BBVA", "40014": "Santander", "40021": "HSBC", "40030": "BanBajío",
    "40036": "Inbursa", "40042": "Mifel", "40044": "Scotiabank", "40058": "Banregio", "40062": "Afirme",
    "40072": "Banorte", "40127": "Banco Azteca", "40130": "Compartamos", "40137": "BanCoppel",
    "40166": "Banco del Bienestar", "90638": "Nu", "90646": "STP", "90722": "Mercado Pago",
}


def payer_from(metadata: dict) -> tuple[str | None, str | None, str | None]:
    """(banco, últimos 4 de la CLABE, clave de rastreo) de quien pagó. Nunca guardamos la CLABE completa."""
    if not isinstance(metadata, dict):
        return None, None, None
    clabe = re.sub(r"\D", "", str(metadata.get("clabe") or ""))
    code = re.sub(r"\D", "", str(metadata.get("bankCode") or ""))
    bank = BANKS.get(code) or (BANKS.get("40" + clabe[:3]) if len(clabe) >= 3 else None)
    tracking = str(metadata.get("trackingKey") or "").strip() or None
    return bank, (clabe[-4:] if len(clabe) >= 4 else None), tracking


def today_summary(limit: int = 50, days: int = 1) -> dict:
    """Pagos desde hace `days` días (1 = solo hoy). Los totales siempre son de hoy y sin simulaciones."""
    today = start_of_today()
    since = today - (max(1, days) - 1) * 86400
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE paid_at >= ? ORDER BY paid_at DESC, rowid DESC LIMIT ?", (since, limit)
        ).fetchall()
        total, count = conn.execute(
            "SELECT COALESCE(SUM(amount),0), COUNT(*) FROM payments WHERE paid_at >= ? AND simulated = 0",
            (today,),
        ).fetchone()
        yesterday = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE paid_at >= ? AND paid_at < ? AND simulated = 0",
            (today - 86400, today),
        ).fetchone()[0]
        # Cobros al celular sin pagar de las últimas 24 h (los vencidos siguen visibles para reenviar)
        pend = conn.execute(
            "SELECT * FROM charges WHERE kind='push' AND status='pending' AND created_at >= ? ORDER BY created_at DESC",
            (int(time.time()) - 86400,),
        ).fetchall()
    return {
        "payments": [payment_to_dict(r) for r in rows],
        "pending": [push_to_dict(r) for r in pend],
        "todayTotal": round(total, 2), "todayCount": count, "yesterdayTotal": round(yesterday, 2),
    }


def push_to_dict(r: sqlite3.Row) -> dict:
    now = int(time.time())
    expires_at = r["created_at"] + r["expiration"]
    return {
        "id": r["id"], "kind": "push", "amount": r["amount"], "concept": r["concept"],
        "phone": r["phone"], "phone4": (r["phone"] or "")[-4:], "saleId": r["sale_id"] or r["id"],
        "createdAt": r["created_at"], "expiresAt": expires_at,
        "status": "pending" if now < expires_at else "expired",
    }


# ---------------------------------------------------------------------------
# SSE: avisar a todas las pantallas/bocinas abiertas
# ---------------------------------------------------------------------------
class Broadcaster:
    def __init__(self) -> None:
        self.queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.queues.discard(q)

    async def publish(self, event: dict) -> None:
        for q in list(self.queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


bus = Broadcaster()

# ---------------------------------------------------------------------------
# Texto hablado: "Recibiste 100 pesos"
# ---------------------------------------------------------------------------
def _qty(n: int) -> str:
    """Número antes de 'peso(s)'/'centavo(s)'. La voz lee '1' como 'uno', pero en español se dice
    'un peso', 'veintiún pesos', 'ciento un pesos'. Para esos casos usamos la palabra; el resto en dígitos."""
    if n % 10 == 1 and n % 100 != 11:
        w = num2words(n, lang="es")
        if w.endswith("veintiuno"):
            return w[: -len("veintiuno")] + "veintiún"
        if w.endswith("uno"):
            return w[:-3] + "un"
        return w
    return f"{n:,}"


def money_words(amount: float) -> str:
    cents = round(float(amount) * 100)
    pesos, cent = divmod(cents, 100)
    parts = []
    if pesos:
        parts.append(f"{_qty(pesos)} {'peso' if pesos == 1 else 'pesos'}")
    if cent:
        parts.append(f"{_qty(cent)} {'centavo' if cent == 1 else 'centavos'}")
    return " con ".join(parts) if parts else "0 pesos"


def _words_apocope(n: int) -> str:
    """Número en letra listo para ir antes de un sustantivo: 'un', 'veintiún', 'treinta y un'."""
    words = num2words(n, lang="es")
    if words.endswith("veintiuno"):
        return words[:-len("veintiuno")] + "veintiún"
    if words == "uno" or words.endswith(" uno"):
        return words[:-3] + "un"
    return words


def amount_letters(amount: float) -> str:
    """Monto en letra para el comprobante: 'Ciento cincuenta pesos con cincuenta centavos'."""
    cents = round(float(amount) * 100)
    pesos, cent = divmod(cents, 100)
    words = _words_apocope(pesos)
    if words.endswith(("millón", "millones")):
        words += " de"
    cents_text = f"{_words_apocope(cent)} {'centavo' if cent == 1 else 'centavos'}"
    if pesos == 0 and cent:
        text = cents_text
    else:
        text = f"{words} {'peso' if pesos == 1 else 'pesos'}"
        if cent:
            text += f" con {cents_text}"
    return text[:1].upper() + text[1:]


def speech_for_amount(amount: float, simulated: bool = False) -> str:
    text = f"Recibiste {money_words(amount)}"
    return f"Simulación. {text}" if simulated else text


# ---------------------------------------------------------------------------
# pey
# ---------------------------------------------------------------------------
async def pey_create_qr(amount: float, concept: str, expiration: int) -> tuple[str, str, str]:
    if not PEY_API_KEY:
        raise HTTPException(400, "Falta PEY_API_KEY en el .env")
    if 0 < expiration < 360:
        expiration = 360  # pey: si hay expiración, el mínimo es 360 s
    num_ref = str(random.randint(1, 9_999_999))  # ^[0-9]{1,7}$
    payload = {
        "amount": amount,  # 0 = el cliente pone el monto al escanear
        "concept": concept,
        "expiration": expiration,
        "numRef": num_ref,
        "generateImage": False,
        "metadata": {},
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{PEY_BASE_URL}/codi/qr", headers={"Authorization": f"Bearer {PEY_API_KEY}"}, json=payload
            )
    except httpx.HTTPError as e:
        raise HTTPException(502, f"No se pudo contactar a pey: {e}") from e
    if r.status_code >= 400:
        log.warning("pey respondió %s: %s", r.status_code, r.text[:500])
        raise HTTPException(502, f"pey respondió {r.status_code}: {r.text[:300]}")
    data = r.json()
    if not data.get("id") or not data.get("qrString"):
        raise HTTPException(502, f"Respuesta inesperada de pey: {str(data)[:300]}")
    return data["id"], data["qrString"], num_ref


class PeyError(HTTPException):
    """Error de pey traducido para el tendero. `code` le dice a la app qué salida ofrecer."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(status, {"code": code, "message": message})


async def pey_push(amount: float, phone: str, concept: str, expiration: int, metadata: dict) -> dict:
    """Solicitud de cobro CoDi al celular del cliente (POST /codi/pn)."""
    if not PEY_API_KEY:
        raise PeyError(400, "config", "Falta PEY_API_KEY en el servidor.")
    payload = {
        "amount": amount, "phoneNumber": phone, "concept": concept,
        "expiration": max(360, expiration), "numRef": str(random.randint(1, 9_999_999)), "metadata": metadata,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{PEY_BASE_URL}/codi/pn", headers={"Authorization": f"Bearer {PEY_API_KEY}"}, json=payload)
    except httpx.HTTPError as e:
        log.warning("No se pudo contactar a pey (push): %s", e)
        raise PeyError(503, "unavailable", "No pudimos conectar con pey. Intenta de nuevo.") from e
    if r.status_code >= 400:
        log.warning("pey push respondió %s: %s", r.status_code, r.text[:500])
        try:
            err = r.json().get("error") or {}
        except ValueError:
            err = {}
        etype, emsg = err.get("type", ""), (err.get("message") or "").lower()
        if r.status_code >= 500:
            raise PeyError(503, "unavailable", "pey no está respondiendo en este momento. Intenta de nuevo.")
        if etype == "INVALID_STATE" or "codi" in emsg and "enabled" in emsg:
            raise PeyError(409, "codi_disabled", "Tu cuenta de pey no tiene habilitado el cobro al celular.")
        if "phone" in emsg or etype in ("INVALID_PARAMETER", "INCOMPLETE_PARAMETERS"):
            raise PeyError(422, "bad_phone", "pey no aceptó ese número. Revísalo con tu cliente.")
        if etype == "INVALID_AMOUNT":
            raise PeyError(422, "bad_amount", "El monto no es válido.")
        raise PeyError(502, "rejected", "pey rechazó el cobro. Intenta de nuevo o usa el QR.")
    data = r.json()
    if not data.get("transactionId"):
        raise PeyError(502, "rejected", "pey respondió algo inesperado. Intenta de nuevo o usa el QR.")
    return data


def clean_phone(raw: str) -> str | None:
    """Acepta '55 1234 5678', '+52 55…', '521…' y deja los 10 dígitos."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 13 and digits.startswith("521"):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith("52"):
        digits = digits[2:]
    return digits if len(digits) == 10 else None


# ---------------------------------------------------------------------------
# API: estado
# ---------------------------------------------------------------------------
def require_admin(request: Request) -> None:
    """Protege Ajustes y acciones de administración con ADMIN_PIN (header X-Admin-Pin)."""
    if not ADMIN_PIN:
        return
    given = request.headers.get("x-admin-pin", "")
    if not hmac.compare_digest(given.encode(), ADMIN_PIN.encode()):
        raise HTTPException(401, "PIN incorrecto")


class PinIn(BaseModel):
    pin: str = Field(default="", max_length=64)


@app.post("/api/admin/check")
async def admin_check(body: PinIn) -> dict:
    if ADMIN_PIN and not hmac.compare_digest(body.pin.encode(), ADMIN_PIN.encode()):
        await asyncio.sleep(0.8)  # frena intentos por fuerza bruta
        raise HTTPException(401, "PIN incorrecto")
    return {"ok": True}


@app.get("/api/status")
async def status() -> dict:
    return {
        "pey": bool(PEY_API_KEY),
        "webhookSecret": bool(PEY_WEBHOOK_SECRET),
        "elevenlabs": bool(ELEVENLABS_API_KEY),
        "claude": bool(ANTHROPIC_API_KEY),
        "allowSimulation": ALLOW_SIMULATION,
        "pinRequired": bool(ADMIN_PIN),
        "fixedLocked": FIXED_LOCKED,
        "defaultExpiration": DEFAULT_EXPIRATION,
        "businessName": BUSINESS_NAME,
        "depositAccount": DEPOSIT_ACCOUNT_LABEL,
        "webhookPath": "/webhooks/pey",
    }


# ---------------------------------------------------------------------------
# API: QR fijo (el de la tiendita)
# ---------------------------------------------------------------------------
class FixedIn(BaseModel):
    name: str = Field(default="", max_length=100)


def _fixed_row():
    with db() as conn:
        return conn.execute(
            "SELECT * FROM charges WHERE kind='fixed' AND status='active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()


def _fixed_dict(row) -> dict:
    return {"id": row["id"], "name": row["concept"], "createdAt": row["created_at"], "qrSvg": qr_svg(row["qr_string"])}


@app.get("/api/fixed-qr")
async def get_fixed_qr() -> dict:
    row = _fixed_row()
    return {"fixed": _fixed_dict(row) if row and row["qr_string"] else None}


@app.post("/api/fixed-qr")
async def create_fixed_qr(body: FixedIn, request: Request) -> dict:
    """Crea un QR fijo nuevo (y retira el anterior de la pantalla).
    Ojo: un QR fijo viejo que ya imprimiste sigue funcionando y sus pagos siguen llegando."""
    require_admin(request)
    if FIXED_LOCKED:
        raise HTTPException(409, "El QR fijo está configurado en el servidor (FIXED_QR_ID / FIXED_QR_STRING).")
    name = (body.name or BUSINESS_NAME).strip() or "Mi tienda"
    qr_id, qr_string, num_ref = await pey_create_qr(0, name, 0)
    now = int(time.time())
    with db() as conn:
        conn.execute("UPDATE charges SET status='retired' WHERE kind='fixed' AND status='active'")
        conn.execute(
            "INSERT OR REPLACE INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, qr_string)"
            " VALUES (?, 0, ?, ?, 'active', ?, 0, 'fixed', ?)",
            (qr_id, name, num_ref, now, qr_string),
        )
    log.info("QR fijo creado %s (%s)", qr_id, name)
    await bus.publish({"type": "fixed"})  # el mostrador recarga su QR
    return {"fixed": _fixed_dict(_fixed_row())}


# ---------------------------------------------------------------------------
# API: cobro con monto
# ---------------------------------------------------------------------------
class ChargeIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    concept: str = Field(default="", max_length=100)
    expiration: int | None = Field(default=None, ge=0)
    saleId: str | None = Field(default=None, max_length=64)  # QR de respaldo de un cobro al celular


def _clean_concept(concept: str) -> tuple[str, str]:
    """(concepto para la app, concepto que ve el cliente en su banco: 'Negocio · concepto')."""
    concept = concept.strip()
    if concept.lower() == "venta":  # el asistente usa "Venta" cuando no hay concepto
        concept = ""
    fixed = _fixed_row()
    biz = (fixed["concept"] if fixed else "") or BUSINESS_NAME
    return concept, (f"{biz} · {concept}"[:100] if concept else biz)


class PushIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    phone: str = Field(min_length=1, max_length=20)
    concept: str = Field(default="", max_length=100)
    saleId: str | None = Field(default=None, max_length=64)  # al reenviar, la misma venta


@app.post("/api/push")
async def create_push(body: PushIn) -> dict:
    """Cobro al celular: pey le manda al cliente una solicitud CoDi a su app del banco."""
    phone = clean_phone(body.phone)
    if not phone:
        raise PeyError(422, "bad_phone", "El número debe tener 10 dígitos.")
    amount = round(body.amount, 2)
    concept, pey_concept = _clean_concept(body.concept)
    data = await pey_push(amount, phone, pey_concept, PUSH_EXPIRATION, {"source": "bocina-codi"})
    tx_id, now = data["transactionId"], int(time.time())
    with db() as conn:
        if body.saleId:  # reenvío: el cobro anterior queda reemplazado
            conn.execute("UPDATE charges SET status='replaced' WHERE kind='push' AND status='pending' AND sale_id=?", (body.saleId,))
        conn.execute(
            "INSERT OR REPLACE INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, phone, sale_id)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?, 'push', ?, ?)",
            (tx_id, amount, concept, data.get("codiId") or "0", now, PUSH_EXPIRATION, phone, body.saleId or tx_id),
        )
        row = conn.execute("SELECT * FROM charges WHERE id=?", (tx_id,)).fetchone()
    log.info("Cobro al celular %s por $%.2f a ···%s", tx_id, amount, phone[-4:])
    await bus.publish({"type": "pending"})
    return push_to_dict(row)


@app.post("/api/push/{charge_id}/dismiss")
async def dismiss_push(charge_id: str) -> dict:
    """Quitar de la lista un cobro al celular que ya no se va a pagar."""
    with db() as conn:
        conn.execute("UPDATE charges SET status='dismissed' WHERE id=? AND kind='push' AND status='pending'", (charge_id,))
    await bus.publish({"type": "pending"})
    return {"ok": True}


@app.post("/api/charges")
async def create_charge(body: ChargeIn) -> dict:
    amount = round(body.amount, 2)
    expiration = DEFAULT_EXPIRATION if body.expiration is None else body.expiration
    concept, pey_concept = _clean_concept(body.concept)
    qr_id, qr_string, num_ref = await pey_create_qr(amount, pey_concept, expiration)
    if 0 < expiration < 360:
        expiration = 360
    now = int(time.time())
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO charges (id, amount, concept, num_ref, status, created_at, expiration, kind, qr_string, sale_id)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?, 'amount', ?, ?)",
            (qr_id, amount, concept, num_ref, now, expiration, qr_string, body.saleId or qr_id),
        )
    log.info("Cobro creado %s por $%.2f (%s)", qr_id, amount, concept)
    # El QR con monto se muestra en el celular del dueño (la App); el mostrador solo tiene el QR fijo.
    return {
        "id": qr_id, "amount": amount, "concept": concept, "numRef": num_ref,
        "expiration": expiration, "createdAt": now, "qrSvg": qr_svg(qr_string),
    }


def _spoken_time(ts: int) -> str:
    t = time.localtime(ts)
    h = t.tm_hour % 12 or 12
    part = "de la mañana" if t.tm_hour < 12 else "de la tarde" if t.tm_hour < 19 else "de la noche"
    return f"a las {h}:{t.tm_min:02d} {part}"


@app.get("/api/last-payment")
async def last_payment() -> dict:
    """Botón 'Último pago' del dispositivo."""
    with db() as conn:
        r = conn.execute("SELECT * FROM payments ORDER BY paid_at DESC, rowid DESC LIMIT 1").fetchone()
    if not r:
        return {"payment": None, "speech": "Todavía no hay pagos."}
    p = payment_to_dict(r)
    sim = "Simulación. " if p["simulated"] else ""
    return {"payment": p, "speech": f"{sim}Último pago: {money_words(p['amount'])}, {_spoken_time(p['paidAt'])}."}


@app.get("/api/payments")
async def list_payments(limit: int = 50, days: int = 1) -> dict:
    return today_summary(min(limit, 500), min(days, 90))


# ---------------------------------------------------------------------------
# Webhook de pey: LA fuente de verdad del pago
# ---------------------------------------------------------------------------
async def handle_payment(payload: dict, *, simulated: bool = False) -> dict:
    # QR: se liga por codiQrId. Cobro al celular: no trae codiQrId, se liga por transactionId (el id que guardamos).
    qr_id = payload.get("codiQrId") or payload.get("transactionId")
    amount = float(payload.get("amount") or 0)
    paid_at = int(payload.get("datePaid") or time.time())
    tx_id = payload.get("transactionId") or f"noid-{time.time_ns()}"

    with db() as conn:
        row = conn.execute("SELECT * FROM charges WHERE id = ?", (qr_id,)).fetchone()
        if not row and payload.get("type") == "codi.pn.payment_received":
            # Respaldo por si el transactionId del aviso no fuera el mismo que nos dio pey al crear la solicitud:
            # el cobro al celular pendiente más reciente con ese monto.
            row = conn.execute(
                "SELECT * FROM charges WHERE kind='push' AND status='pending' AND ABS(amount - ?) < 0.001"
                " AND created_at >= ? ORDER BY created_at DESC LIMIT 1",
                (amount, int(time.time()) - 86400),
            ).fetchone()
            if row:
                qr_id = row["id"]
        kind = row["kind"] if row else "external"
        # Preferimos el concepto que guardamos nosotros (el webhook puede traer "Negocio · concepto")
        concept = row["concept"] if row else (payload.get("concept") or "")
        phone4 = (row["phone"] or "")[-4:] if row and kind == "push" else None
        payer_bank, payer_clabe4, tracking_key = payer_from(payload.get("metadata") or {})
        # ¿Esta venta ya estaba pagada? (p. ej. pagó el QR de respaldo y también la solicitud al celular)
        sale_id = (row["sale_id"] or row["id"]) if row and kind in ("amount", "push") else None
        dup_sale = bool(sale_id) and conn.execute(
            "SELECT 1 FROM payments p JOIN charges c ON c.id = p.codi_qr_id"
            " WHERE COALESCE(c.sale_id, c.id) = ? AND p.transaction_id != ? LIMIT 1", (sale_id, tx_id),
        ).fetchone() is not None
        inserted = conn.execute(
            "INSERT OR IGNORE INTO payments (transaction_id, codi_qr_id, kind, amount, concept, paid_at, simulated, phone4,"
            " duplicate_sale, payer_bank, payer_clabe4, tracking_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tx_id, qr_id, kind, amount, concept, paid_at, int(simulated), phone4, int(dup_sale),
             payer_bank, payer_clabe4, tracking_key),
        ).rowcount
        if row and kind in ("amount", "push"):
            conn.execute(
                "UPDATE charges SET status='paid', paid_at=?, paid_amount=?, transaction_id=?, simulated=? WHERE id=?",
                (paid_at, amount, tx_id, int(simulated), qr_id),
            )

    event = {
        "type": "payment",
        "verified": not simulated,
        "simulated": simulated,
        "duplicate": not inserted,
        "chargeId": qr_id,
        "kind": kind,  # fixed | amount | push | external
        "phone4": phone4,
        "duplicateSale": dup_sale,
        "payerBank": payer_bank,
        "payerClabe4": payer_clabe4,
        "trackingKey": tracking_key,
        "amount": amount,
        "amountWords": amount_letters(amount),
        "expectedAmount": row["amount"] if row and kind in ("amount", "push") else None,
        "concept": concept,
        "transactionId": tx_id,
        "datePaid": paid_at,
        "speech": speech_for_amount(amount, simulated),
    }
    if inserted:
        await bus.publish(event)
        log.info("PAGO %s %s: $%.2f qr=%s tx=%s", kind, "SIMULADO" if simulated else "VERIFICADO", amount, qr_id, tx_id)
    return event


@app.post("/", include_in_schema=False)  # por si la URL del webhook quedó sin /webhooks/pey
@app.post("/webhooks/pey")
async def pey_webhook(request: Request) -> JSONResponse:
    raw = (await request.body()).decode("utf-8")
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not PEY_WEBHOOK_SECRET:
        log.error("Llegó un webhook pero falta PEY_WEBHOOK_SECRET; no se puede verificar")
        return JSONResponse({"error": "webhook secret not configured"}, status_code=503)

    # 1) Firma sobre el cuerpo crudo
    try:
        Webhook(PEY_WEBHOOK_SECRET).verify(raw, headers)
    except Exception as e:
        log.warning("Webhook rechazado (firma inválida): %s", e)
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    # 2) Idempotencia por webhook-id
    webhook_id = headers.get("webhook-id") or f"noid-{time.time_ns()}"
    payload = json.loads(raw)
    event_type = payload.get("type", "")
    with db() as conn:
        if conn.execute("SELECT 1 FROM webhook_events WHERE webhook_id=?", (webhook_id,)).fetchone():
            return JSONResponse({"ok": True, "duplicate": True})
        conn.execute(
            "INSERT INTO webhook_events (webhook_id, received_at, type, payload) VALUES (?, ?, ?, ?)",
            (webhook_id, int(time.time()), event_type, raw),
        )

    # 3) Procesar
    if event_type in ("codi.qr.payment_received", "codi.pn.payment_received"):
        await handle_payment(payload)
    else:
        log.info("Webhook %s recibido (sin manejador): %s", event_type, raw[:300])
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------
@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    q = bus.subscribe()

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


# ---------------------------------------------------------------------------
# Voz de salida: ElevenLabs
# ---------------------------------------------------------------------------
class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)


_tts_cache: dict[str, bytes] = {}


@app.post("/api/tts")
async def tts(body: TTSIn) -> Response:
    if not ELEVENLABS_API_KEY:
        raise HTTPException(400, "Falta ELEVENLABS_API_KEY")
    key = f"{ELEVENLABS_VOICE_ID}:{body.text}"
    if key not in _tts_cache:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": ELEVENLABS_API_KEY},
                json={"text": body.text, "model_id": ELEVENLABS_MODEL, "language_code": "es"},
            )
        if r.status_code >= 400:
            log.warning("ElevenLabs %s: %s", r.status_code, r.text[:300])
            raise HTTPException(502, f"ElevenLabs {r.status_code}: {r.text[:300]}")
        if len(_tts_cache) > 300:
            _tts_cache.clear()
        _tts_cache[key] = r.content
    return Response(_tts_cache[key], media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# Asistente de voz: cobrar o preguntar
# ---------------------------------------------------------------------------
class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)


ASSISTANT_SYSTEM = """Eres pey, el asistente de voz de la caja de una tiendita en México.
El tendero te habla. Decide si quiere COBRAR o PREGUNTAR algo sobre sus ventas.

Responde SOLO con JSON válido, sin texto extra:
{"intent": "charge" | "query" | "unknown", "amount": number|null, "concept": string|null, "answer": string}

- charge: quiere generar un cobro con monto ("cóbrale 90", "dos tortas de 45" -> 90). Si da cantidad y
  precio unitario, multiplica. concept corto ("2 tortas"; "Venta" si no dice). answer: "".
- query: pregunta por ventas, pagos, totales, último pago, etc. Contesta en "answer" usando SOLO los datos
  que te paso; no inventes. Respuesta corta para decirse en voz alta (1-2 frases), en español de México,
  montos con número y la palabra pesos (ej. "85 pesos", "1,250 pesos con 50 centavos"), horas como "1:24 de la tarde".
- unknown: no entendiste. answer: una frase corta pidiendo que repita.
"""


def _hhmm(ts: int) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def _context_for_assistant() -> str:
    s = today_summary(limit=15)
    lines = [
        f"Hora actual: {time.strftime('%H:%M')}",
        f"Total verificado hoy: {money_words(s['todayTotal'])} en {s['todayCount']} pagos",
        "Pagos de hoy (más reciente primero):",
    ]
    for p in s["payments"]:
        tipo = {"fixed": "QR fijo", "amount": "cobro con monto", "push": "cobro al celular", "external": "QR externo"}.get(p["kind"], p["kind"])
        sim = " (SIMULADO, no cuenta)" if p["simulated"] else ""
        lines.append(f"- {_hhmm(p['paidAt'])} · {money_words(p['amount'])} · {p['concept'] or 'sin concepto'} · {tipo}{sim}")
    if not s["payments"]:
        lines.append("- (sin pagos hoy)")
    return "\n".join(lines)


def _fallback_assistant(text: str) -> dict:
    """Sin Claude: reglas simples para que el demo no se caiga."""
    t = text.lower()
    s = today_summary(limit=10)
    if any(w in t for w in ("cuánto", "cuanto", "total", "vendí", "vendi", "llevo")):
        return {"intent": "query", "amount": None, "concept": None,
                "answer": f"Hoy llevas {money_words(s['todayTotal'])} en {s['todayCount']} pagos."}
    if "últim" in t or "ultim" in t:
        m = re.search(r"\d+", t)
        n = min(int(m.group()) if m else 3, 10)
        ps = [p for p in s["payments"] if not p["simulated"]][:n]
        if not ps:
            return {"intent": "query", "amount": None, "concept": None, "answer": "Hoy todavía no hay pagos."}
        items = "; ".join(f"{money_words(p['amount'])} a las {_hhmm(p['paidAt'])}" for p in ps)
        return {"intent": "query", "amount": None, "concept": None, "answer": f"Tus últimos pagos: {items}."}
    m = re.search(r"\$?\s*(\d+(?:[.,]\d{1,2})?)", t)
    if m:
        return {"intent": "charge", "amount": float(m.group(1).replace(",", ".")), "concept": "Venta", "answer": ""}
    return {"intent": "unknown", "amount": None, "concept": None, "answer": "No te entendí, ¿me lo repites?"}


@app.post("/api/assistant")
async def assistant(body: AskIn) -> dict:
    if not ANTHROPIC_API_KEY:
        return {**_fallback_assistant(body.text), "source": "reglas"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 300,
                    "system": ASSISTANT_SYSTEM,
                    "messages": [{"role": "user", "content": f"DATOS:\n{_context_for_assistant()}\n\nEL TENDERO DIJO: {body.text}"}],
                },
            )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        amount = data.get("amount")
        return {
            "intent": data.get("intent", "unknown"),
            "amount": round(float(amount), 2) if amount else None,
            "concept": (data.get("concept") or "Venta")[:100],
            "answer": (data.get("answer") or "")[:400],
            "source": "claude",
        }
    except Exception as e:
        log.warning("Asistente con Claude falló, uso reglas: %s", e)
        return {**_fallback_assistant(body.text), "source": "reglas"}


# ---------------------------------------------------------------------------
# Simulación (solo pruebas; desactivada por defecto)
# ---------------------------------------------------------------------------
@app.post("/api/dev/simulate/{charge_id}")
async def simulate(charge_id: str, request: Request, amount: float | None = None) -> dict:
    require_admin(request)
    if not ALLOW_SIMULATION:
        raise HTTPException(403, "Simulación desactivada (ALLOW_SIMULATION=false)")
    with db() as conn:
        row = conn.execute("SELECT * FROM charges WHERE id = ?", (charge_id,)).fetchone()
    if not row:
        raise HTTPException(404, "QR no encontrado")
    amt = amount if row["kind"] == "fixed" else row["amount"]
    if not amt or amt <= 0:
        amt = round(random.choice([12, 18.5, 25, 37, 85]), 2)
    if row["kind"] == "push":  # el aviso real de pey no trae codiQrId: se liga por transactionId
        return await handle_payment(
            {"type": "codi.pn.payment_received", "amount": amt, "concept": row["concept"],
             "datePaid": int(time.time()), "transactionId": charge_id},
            simulated=True,
        )
    return await handle_payment(
        {"type": "codi.qr.payment_received", "codiQrId": charge_id, "amount": amt, "concept": row["concept"],
         "datePaid": int(time.time()), "transactionId": f"SIM-{time.time_ns()}"},
        simulated=True,
    )


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def mostrador() -> FileResponse:
    """La bocina: solo el QR y el botón de voz."""
    return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE)


@app.get("/app")
@app.get("/caja", include_in_schema=False)
async def owner_app() -> FileResponse:
    """La App del dueño (pensada para celular): pagos del día, cobro con monto, asistente y ajustes."""
    return FileResponse(STATIC_DIR / "app.html", headers=NO_CACHE)


@app.get("/api/qr.svg", include_in_schema=False)
async def any_qr(text: str) -> Response:
    """QR genérico (p. ej. para abrir la App en el celular desde la pantalla de la computadora)."""
    if len(text) > 500:
        raise HTTPException(400, "Texto demasiado largo")
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=6, border=4)  # SVG completo (con xmlns) para <img>
    return Response(buf.getvalue(), media_type="image/svg+xml")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest() -> JSONResponse:
    """Permite 'Instalar app' / 'Agregar a pantalla de inicio' en Chrome y Android."""
    return JSONResponse(
        {
            "name": "Bocina CoDi",
            "short_name": "Bocina",
            "description": "Tu QR de CoDi que te avisa en voz alta cada pago.",
            "start_url": "/app",
            "display": "standalone",
            "background_color": "#f6f4ef",
            "theme_color": "#f6f4ef",
            "icons": [{"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
        },
        media_type="application/manifest+json",
    )
