"""Cliente de la API de pey (https://docs.pey.mx)."""

import logging
import random
import re

import httpx
from fastapi import HTTPException

from app import config

log = logging.getLogger("bocina")


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.PEY_API_KEY}"}


class PeyError(HTTPException):
    """Error de pey traducido para el tendero. `code` le dice a la app qué salida ofrecer."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(status, {"code": code, "message": message})


async def create_qr(amount: float, concept: str, expiration: int, bank_account_id: str | None = None) -> tuple[str, str, str]:
    """`bank_account_id`: la CLABE del negocio registrada en pey. Sin él, el dinero cae en la cuenta de la API key."""
    if not config.PEY_API_KEY:
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
    if bank_account_id:
        payload["bankAccountId"] = bank_account_id
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{config.PEY_BASE_URL}/codi/qr", headers=_headers(), json=payload)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"No se pudo contactar a pey: {e}") from e
    if r.status_code >= 400:
        log.warning("pey respondió %s: %s", r.status_code, r.text[:500])
        raise HTTPException(502, f"pey respondió {r.status_code}: {r.text[:300]}")
    data = r.json()
    if not data.get("id") or not data.get("qrString"):
        raise HTTPException(502, f"Respuesta inesperada de pey: {str(data)[:300]}")
    return data["id"], data["qrString"], num_ref


async def push(amount: float, phone: str, concept: str, expiration: int, metadata: dict,
               bank_account_id: str | None = None) -> dict:
    """Solicitud de cobro CoDi al celular del cliente (POST /codi/pn)."""
    if not config.PEY_API_KEY:
        raise PeyError(400, "config", "Falta PEY_API_KEY en el servidor.")
    payload = {
        "amount": amount, "phoneNumber": phone, "concept": concept,
        "expiration": max(360, expiration), "numRef": str(random.randint(1, 9_999_999)), "metadata": metadata,
    }
    if bank_account_id:
        payload["bankAccountId"] = bank_account_id
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{config.PEY_BASE_URL}/codi/pn", headers=_headers(), json=payload)
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


# --- Cuentas bancarias de los negocios ---------------------------------------
async def register_bank_account(alias: str, name: str, clabe: str) -> dict:
    """POST /bank-account: registra la CLABE del negocio. Queda PENDING; pey la da de alta en Banxico
    (hasta 5 días hábiles) y avisa con el webhook bank.account.updated cuando pasa a ACTIVE."""
    if not config.PEY_API_KEY:
        raise PeyError(503, "config", "Falta PEY_API_KEY en el servidor.")
    payload = {"alias": alias[:255], "name": name[:255], "clabe": clabe, "entity": "PERSON"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{config.PEY_BASE_URL}/bank-account", headers=_headers(), json=payload)
    except httpx.HTTPError as e:
        log.warning("No se pudo contactar a pey (bank-account): %s", e)
        raise PeyError(503, "unavailable", "No pudimos conectar con pey. Intenta de nuevo.") from e
    if r.status_code >= 400:
        log.warning("pey bank-account respondió %s: %s", r.status_code, r.text[:500])
        if r.status_code >= 500 or r.status_code == 429:
            raise PeyError(503, "unavailable", "pey no está respondiendo en este momento. Intenta de nuevo.")
        try:
            msg = (r.json().get("error") or {}).get("message") or ""
        except ValueError:
            msg = ""
        if "clabe" in msg.lower() or "codi" in msg.lower() or "bank" in msg.lower():
            raise PeyError(422, "bad_clabe", "pey no aceptó esa CLABE. Revisa que sea correcta y que tu banco tenga CoDi.")
        raise PeyError(422, "rejected", "pey no pudo registrar tu cuenta. Revisa tus datos.")
    data = r.json()
    if not data.get("id"):
        raise PeyError(502, "rejected", "pey respondió algo inesperado. Intenta de nuevo.")
    return data


async def get_bank_account(bank_account_id: str) -> dict:
    """GET /bank-account/{id}: estado del alta en CoDi (PENDING | PROCESSING | ACTIVE | ERROR)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{config.PEY_BASE_URL}/bank-account/{bank_account_id}", headers=_headers())
    r.raise_for_status()
    return r.json()


# --- Consultas para el respaldo del webhook ---------------------------------
async def list_bank_account_transactions(client: httpx.AsyncClient, bank_account_id: str,
                                         next_token: str | None = None) -> dict:
    """GET /transaction/bank-account/{id}: pagos de una cuenta (QR y cobro al celular), 80 por página.
    Item: {id, status, amount, payableType (API_CODI_QR|API_CODI_PN), payableId, datePaid, metadata, ...}."""
    r = await client.get(
        f"{config.PEY_BASE_URL}/transaction/bank-account/{bank_account_id}",
        params={"nextToken": next_token} if next_token else None, headers=_headers(),
    )
    r.raise_for_status()
    return r.json()


async def list_qr_transactions(client: httpx.AsyncClient, qr_id: str, next_token: str | None = None) -> dict:
    """GET /transaction/codi/qr/{qrId}: pagos de un QR, 20 por página, el más reciente primero.
    Cada item: {id, status, amount, description, dateCreated, datePaid, metadata}. `id` = transactionId del webhook."""
    r = await client.get(
        f"{config.PEY_BASE_URL}/transaction/codi/qr/{qr_id}",
        params={"nextToken": next_token} if next_token else None, headers=_headers(),
    )
    r.raise_for_status()
    return r.json()


async def get_transaction(client: httpx.AsyncClient, tx_id: str) -> dict:
    """GET /transaction/{id}: estado de una transacción (PENDING | PAID). Sirve para el cobro al celular."""
    r = await client.get(f"{config.PEY_BASE_URL}/transaction/{tx_id}", headers=_headers())
    r.raise_for_status()
    return r.json()


def clean_phone(raw: str) -> str | None:
    """Acepta '55 1234 5678', '+52 55…', '521…' y deja los 10 dígitos."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 13 and digits.startswith("521"):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith("52"):
        digits = digits[2:]
    return digits if len(digits) == 10 else None
