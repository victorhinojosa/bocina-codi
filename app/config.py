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
BUSINESS_NAME = env("BUSINESS_NAME", "Mi tienda")  # nombre del negocio demo
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
# Voz de Din: la misma para los audios pregenerados (app/static/voice/<voz>/) y para lo que se genera en vivo
ELEVENLABS_VOICE_ID = env("ELEVENLABS_VOICE_ID", "ewn5JTa3lNPY8QVuZJi6")
ELEVENLABS_MODEL = env("ELEVENLABS_MODEL", "eleven_flash_v2_5")

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-haiku-5-5")

ALLOW_SIMULATION = env("ALLOW_SIMULATION", "false").lower() == "true"

# QR fijo de la cuenta demo, amarrado por variables de entorno (sobrevive reinicios y deploys)
FIXED_QR_ID = env("FIXED_QR_ID")
FIXED_QR_STRING = env("FIXED_QR_STRING")

DB_PATH = env("DB_PATH", str(ROOT / "bocina.db"))

# Cuenta demo (Ramón): sus credenciales se muestran en /app en computadora para que cualquiera entre.
# Usa la cuenta CoDi de la API key (sin bankAccountId) y hereda los pagos que había antes de las cuentas.
DEMO_PHONE = env("DEMO_PHONE")
DEMO_PIN = env("DEMO_PIN")
DEMO_FIRST_NAME = env("DEMO_FIRST_NAME", "Ramón")
DEMO_LAST_NAME = env("DEMO_LAST_NAME", "Demo")
# Límites del cobro al celular en la cuenta demo (manda una solicitud real a un celular real)
DEMO_PUSH_PER_SESSION = int(env("DEMO_PUSH_PER_SESSION", "3"))
DEMO_PUSH_PER_DAY = int(env("DEMO_PUSH_PER_DAY", "30"))
DEMO_PUSH_MAX_AMOUNT = float(env("DEMO_PUSH_MAX_AMOUNT", "50"))

SESSION_DAYS = int(env("SESSION_DAYS", "90"))

# Administración de la plataforma (/api/admin/...). Vacío = apagada. Usa un valor largo y aleatorio.
ADMIN_TOKEN = env("ADMIN_TOKEN")

# URL pública del servidor (https://...) para las páginas de regreso del link de pago.
# Vacío = se toma del proxy (Railway). Útil con ngrok.
PUBLIC_URL = env("PUBLIC_URL")
