"""Frontend: páginas, QR genérico y manifiesto de la app instalable."""

import io

import segno
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from app import auth, config

router = APIRouter()

# Las páginas se revalidan en cada carga para que nadie vea una versión vieja en caché
NO_CACHE = {"Cache-Control": "no-cache"}


@router.get("/")
async def home(request: Request) -> FileResponse:
    """La landing de Din. Una bocina ya vinculada (cookie de dispositivo) sigue abriendo la bocina aquí."""
    v = auth.current_viewer(request)
    if v and v.is_device:
        return FileResponse(config.STATIC_DIR / "index.html", headers=NO_CACHE)
    return FileResponse(config.STATIC_DIR / "landing.html", headers=NO_CACHE)


@router.get("/bocina")
async def mostrador() -> FileResponse:
    """La bocina (Din Box): solo el QR y el botón de voz."""
    return FileResponse(config.STATIC_DIR / "index.html", headers=NO_CACHE)


@router.get("/api/demo-qr.svg", include_in_schema=False)
async def demo_qr() -> Response:
    """QR fijo real de la cuenta demo, para pagar $1 desde la landing. 404 si no hay demo configurada."""
    if not config.FIXED_QR_STRING:
        raise HTTPException(404, "Sin QR demo")
    buf = io.BytesIO()
    segno.make(config.FIXED_QR_STRING, error="m").save(buf, kind="svg", scale=6, border=2, dark="#0B1A33")
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/app")
@router.get("/caja", include_in_schema=False)
async def owner_app() -> FileResponse:
    """La App del dueño (pensada para celular): pagos del día, cobro con monto, asistente y ajustes."""
    return FileResponse(config.STATIC_DIR / "app.html", headers=NO_CACHE)


@router.get("/demo")
async def demo_page() -> FileResponse:
    """Demo para presentar: la bocina y la app del dueño lado a lado, reaccionando al mismo pago."""
    return FileResponse(config.STATIC_DIR / "demo.html", headers=NO_CACHE)


@router.get("/api/qr.svg", include_in_schema=False)
async def any_qr(text: str) -> Response:
    """QR genérico (p. ej. para abrir la App en el celular desde la pantalla de la computadora)."""
    if len(text) > 500:
        raise HTTPException(400, "Texto demasiado largo")
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=6, border=4)  # SVG completo (con xmlns) para <img>
    return Response(buf.getvalue(), media_type="image/svg+xml")


@router.get("/manifest.webmanifest", include_in_schema=False)
async def manifest() -> JSONResponse:
    """Permite 'Instalar app' / 'Agregar a pantalla de inicio' en Chrome y Android."""
    return JSONResponse(
        {
            "name": "Din",
            "short_name": "Din",
            "description": "Tu QR de CoDi que te avisa en voz alta cada pago.",
            "start_url": "/app",
            "display": "standalone",
            "background_color": "#F4F6FA",
            "theme_color": "#F4F6FA",
            "icons": [
                {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
                {"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
            ],
        },
        media_type="application/manifest+json",
    )
