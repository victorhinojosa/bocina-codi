"""
Bocina CoDi — la caja que te dice en voz alta cuando te pagaron.

Dos formas de cobrar con pey/CoDi:
  * QR FIJO   (amount=0, sin expiración): el cliente escanea y pone el monto. Como en las
                tienditas de India. Un solo QR recibe muchos pagos.
  * CON MONTO (amount>0): un QR por cobro, para tickets grandes, pedidos o proveedores.

La confirmación sale de un webhook de pey con firma válida (Standard Webhooks). Si el webhook no
llega, el respaldo (recovery.py) consulta a pey y recupera el pago. Cada pago se guarda una sola vez
en la tabla `payments`, con su transactionId como clave.

Módulos:
  config     variables de entorno            db         tablas y migraciones
  timeutil   horas en la zona del negocio    speech     montos y frases habladas
  pey        cliente de la API de pey        payments   registrar, anunciar e historial
  recovery   respaldo del webhook            events     SSE a las pantallas
  routes/    endpoints HTTP
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.recovery import recovery
from app.routes import charges, history, pages, system, voice, webhooks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bocina")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    db.seed_fixed_qr()
    if not db.storage_is_persistent():
        log.warning(
            "⚠ La base de datos (%s) NO está en un volumen: el historial de pagos se borrará en cada despliegue. "
            "En Railway agrega un volumen en /data y define DB_PATH=/data/bocina.db.", config.DB_PATH,
        )
    log.info("Zona horaria del negocio: %s", config.BUSINESS_TZ)
    task = None
    if config.PEY_API_KEY and config.RECOVERY_POLL_SECONDS > 0:
        task = asyncio.create_task(recovery.run())
        log.info("Respaldo del webhook: cada %d s mientras haya pantallas conectadas", config.RECOVERY_POLL_SECONDS)
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Bocina CoDi", lifespan=lifespan)


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """Los JS/CSS propios se revalidan (304 si no cambiaron); three.js sí se cachea."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") and not path.startswith("/static/vendor/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


for module in (system, charges, history, webhooks, voice, pages):
    app.include_router(module.router)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
