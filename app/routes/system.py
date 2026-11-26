"""Estado del servidor (público: no dice nada de ningún negocio, salvo las credenciales de la demo)."""

from fastapi import APIRouter

from app import config, db, voice

router = APIRouter()


@router.get("/api/status")
async def status() -> dict:
    return {
        "pey": bool(config.PEY_API_KEY),
        "webhookSecret": bool(config.PEY_WEBHOOK_SECRET),
        "elevenlabs": bool(config.ELEVENLABS_API_KEY),
        "claude": bool(config.ANTHROPIC_API_KEY),
        "allowSimulation": config.ALLOW_SIMULATION,
        "persistentStorage": db.storage_is_persistent(),
        "defaultExpiration": config.DEFAULT_EXPIRATION,
        "timezone": config.BUSINESS_TZ,
        "recoveryPollSeconds": config.RECOVERY_POLL_SECONDS,
        "webhookPath": "/webhooks/pey",
        # Voz pregenerada: si están todos los audios de esta voz, el navegador arma los anuncios con ellos
        "voice": {"id": config.ELEVENLABS_VOICE_ID, "clips": voice.available()},
        # La cuenta demo es pública a propósito: se muestra en /app en computadora para que cualquiera entre
        "demo": {"phone": config.DEMO_PHONE, "pin": config.DEMO_PIN, "name": config.DEMO_FIRST_NAME,
                 "pushPerSession": config.DEMO_PUSH_PER_SESSION, "pushMaxAmount": config.DEMO_PUSH_MAX_AMOUNT}
        if config.DEMO_PHONE and config.DEMO_PIN else None,
    }
