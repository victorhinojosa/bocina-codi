"""Voz de salida (ElevenLabs) y asistente de voz: cobrar o preguntar."""

import json
import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import auth, config, timeutil
from app.auth import Viewer
from app.payments import today_summary
from app.speech import money_words

log = logging.getLogger("bocina")
router = APIRouter()


# --- ElevenLabs -------------------------------------------------------------
class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)


_tts_cache: dict[str, bytes] = {}


@router.post("/api/tts")
async def tts(body: TTSIn, v: Viewer = Depends(auth.viewer)) -> Response:
    if not config.ELEVENLABS_API_KEY:
        raise HTTPException(400, "Falta ELEVENLABS_API_KEY")
    key = f"{config.ELEVENLABS_VOICE_ID}:{body.text}"
    if key not in _tts_cache:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": config.ELEVENLABS_API_KEY},
                json={"text": body.text, "model_id": config.ELEVENLABS_MODEL, "language_code": "es"},
            )
        if r.status_code >= 400:
            log.warning("ElevenLabs %s: %s", r.status_code, r.text[:300])
            raise HTTPException(502, f"ElevenLabs {r.status_code}: {r.text[:300]}")
        if len(_tts_cache) > 300:
            _tts_cache.clear()
        _tts_cache[key] = r.content
    return Response(_tts_cache[key], media_type="audio/mpeg")


# --- Asistente --------------------------------------------------------------
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
  montos con número y la palabra pesos (ej. "85 pesos", "1,250 pesos con 50 centavos"). Las horas dilas
  en palabras, tal como vienen en los datos (ej. "a la una y veinticuatro de la tarde"), nunca "1:24".
- unknown: no entendiste. answer: una frase corta pidiendo que repita.
"""


def _context_for_assistant(merchant_id: str) -> str:
    s = today_summary(merchant_id, limit=15)
    lines = [
        f"Hora actual: {timeutil.spoken_time(timeutil.now_ts())}",
        f"Total verificado hoy: {money_words(s['todayTotal'])} en {s['todayCount']} pagos",
        "Pagos de hoy (más reciente primero):",
    ]
    for p in s["payments"]:
        tipo = {"fixed": "QR fijo", "amount": "cobro con monto", "push": "cobro al celular", "external": "QR externo"}.get(p["kind"], p["kind"])
        sim = " (SIMULADO, no cuenta)" if p["simulated"] else ""
        lines.append(f"- {timeutil.spoken_time(p['paidAt'])} · {money_words(p['amount'])} · {p['concept'] or 'sin concepto'} · {tipo}{sim}")
    if not s["payments"]:
        lines.append("- (sin pagos hoy)")
    return "\n".join(lines)


def fallback_assistant(text: str, merchant_id: str) -> dict:
    """Sin Claude: reglas simples para que el demo no se caiga."""
    t = text.lower()
    s = today_summary(merchant_id, limit=10)
    if any(w in t for w in ("cuánto", "cuanto", "total", "vendí", "vendi", "llevo")):
        return {"intent": "query", "amount": None, "concept": None,
                "answer": f"Hoy llevas {money_words(s['todayTotal'])} en {s['todayCount']} pagos."}
    if "últim" in t or "ultim" in t:
        m = re.search(r"\d+", t)
        n = min(int(m.group()) if m else 3, 10)
        ps = [p for p in s["payments"] if not p["simulated"]][:n]
        if not ps:
            return {"intent": "query", "amount": None, "concept": None, "answer": "Hoy todavía no hay pagos."}
        items = "; ".join(f"{money_words(p['amount'])} {timeutil.spoken_time(p['paidAt'])}" for p in ps)
        return {"intent": "query", "amount": None, "concept": None, "answer": f"Tus últimos pagos: {items}."}
    m = re.search(r"\$?\s*(\d+(?:[.,]\d{1,2})?)", t)
    if m:
        return {"intent": "charge", "amount": float(m.group(1).replace(",", ".")), "concept": "Venta", "answer": ""}
    return {"intent": "unknown", "amount": None, "concept": None, "answer": "No te entendí, ¿me lo repites?"}


@router.post("/api/assistant")
async def assistant(body: AskIn, v: Viewer = Depends(auth.viewer)) -> dict:
    if not config.ANTHROPIC_API_KEY:
        return {**fallback_assistant(body.text, v.merchant_id), "source": "reglas"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={
                    "model": config.CLAUDE_MODEL,
                    "max_tokens": 300,
                    "system": ASSISTANT_SYSTEM,
                    "messages": [{"role": "user", "content": f"DATOS:\n{_context_for_assistant(v.merchant_id)}\n\nEL TENDERO DIJO: {body.text}"}],
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
        return {**fallback_assistant(body.text, v.merchant_id), "source": "reglas"}
