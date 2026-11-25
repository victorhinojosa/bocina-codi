"""Configuración desde variables de entorno. Las llaves viven en el servidor; nunca llegan al navegador.

Los demás módulos leen `config.X` en el momento de usarlo (no `from config import X`), así las pruebas
pueden cambiar un valor con monkeypatch sin recargar nada.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def env(name: str, default: str = "") -> str:
    """Variable de entorno; si está vacía usa el valor por defecto (así `DB_PATH=` en el .env no rompe nada)."""
    v = os.getenv(name, "").strip()
    return v if v else default


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

PEY_API_KEY = env("PEY_API_KEY")
PEY_BASE_URL = env("PEY_BASE_URL", "https://api.pey.mx").rstrip("/")
PEY_WEBHOOK_SECRET = env("PEY_WEBHOOK_SECRET")  # whsec_...
DEFAULT_EXPIRATION = int(env("DEFAULT_EXPIRATION", "0"))  # 0 = sin expiración; si se pone, mínimo 360
BUSINESS_NAME = env("BUSINESS_NAME", "Mi tienda")
# Zona horaria del negocio: con ella se dicen las horas y se calcula "hoy". El servidor (Railway) corre en UTC.
BUSINESS_TZ = env("BUSINESS_TZ", "America/Mexico_City")
# Etiqueta de la cuenta donde cae el dinero, solo para mostrar en el perfil (ej. "BBVA ···· 2702"). Opcional.
DEPOSIT_ACCOUNT_LABEL = env("DEPOSIT_ACCOUNT_LABEL")
# Cuánto dura una solicitud de cobro al celular (CoDi push). pey exige mínimo 360 s.
PUSH_EXPIRATION = max(360, int(env("PUSH_EXPIRATION", "900")))

# Respaldo del webhook: cada cuánto se consulta a pey mientras haya una pantalla conectada (0 = apagado)
RECOVERY_POLL_SECONDS = int(env("RECOVERY_POLL_SECONDS", "45"))
# Solo se anuncian en voz los pagos de los últimos N segundos; los más viejos van directo al historial
ANNOUNCE_WINDOW_SECONDS = int(env("ANNOUNCE_WINDOW_SECONDS", "120"))

ELEVENLABS_API_KEY = env("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = env("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_MODEL = env("ELEVENLABS_MODEL", "eleven_flash_v2_5")

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-haiku-5-5")

ALLOW_SIMULATION = env("ALLOW_SIMULATION", "false").lower() == "true"

# PIN para Ajustes y acciones de administración (vacío = sin PIN, útil en local)
ADMIN_PIN = env("ADMIN_PIN")

# QR fijo amarrado a la cuenta: si se definen, el servidor siempre usa este QR (sobrevive reinicios y deploys)
FIXED_QR_ID = env("FIXED_QR_ID")
FIXED_QR_STRING = env("FIXED_QR_STRING")
FIXED_LOCKED = bool(FIXED_QR_ID and FIXED_QR_STRING)

DB_PATH = env("DB_PATH", str(ROOT / "bocina.db"))
