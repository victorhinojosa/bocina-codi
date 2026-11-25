"""Estado del servidor y PIN de administración."""

import asyncio
import hmac

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import config, db

router = APIRouter()


def require_admin(request: Request) -> None:
    """Protege Ajustes y acciones de administración con ADMIN_PIN (header X-Admin-Pin)."""
    if not config.ADMIN_PIN:
        return
    given = request.headers.get("x-admin-pin", "")
    if not hmac.compare_digest(given.encode(), config.ADMIN_PIN.encode()):
        raise HTTPException(401, "PIN incorrecto")


class PinIn(BaseModel):
    pin: str = Field(default="", max_length=64)


@router.post("/api/admin/check")
async def admin_check(body: PinIn) -> dict:
    if config.ADMIN_PIN and not hmac.compare_digest(body.pin.encode(), config.ADMIN_PIN.encode()):
        await asyncio.sleep(0.8)  # frena intentos por fuerza bruta
        raise HTTPException(401, "PIN incorrecto")
    return {"ok": True}


@router.get("/api/status")
async def status() -> dict:
    return {
        "pey": bool(config.PEY_API_KEY),
        "webhookSecret": bool(config.PEY_WEBHOOK_SECRET),
        "elevenlabs": bool(config.ELEVENLABS_API_KEY),
        "claude": bool(config.ANTHROPIC_API_KEY),
        "allowSimulation": config.ALLOW_SIMULATION,
        "persistentStorage": db.storage_is_persistent(),
        "pinRequired": bool(config.ADMIN_PIN),
        "fixedLocked": config.FIXED_LOCKED,
        "defaultExpiration": config.DEFAULT_EXPIRATION,
        "businessName": config.BUSINESS_NAME,
        "depositAccount": config.DEPOSIT_ACCOUNT_LABEL,
        "timezone": config.BUSINESS_TZ,
        "recoveryPollSeconds": config.RECOVERY_POLL_SECONDS,
        "webhookPath": "/webhooks/pey",
    }
