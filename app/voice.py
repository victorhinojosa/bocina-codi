"""Voz pregenerada: los anuncios se arman con audios cortos generados una sola vez con ElevenLabs.

"Recibiste · cincuenta · pesos · con · veinte · centavos" son 6 audios que el navegador reproduce seguidos.
Así un pago nunca llama a ElevenLabs. Los audios viven en app/static/voice/<voice_id>/ (los genera
scripts/generate_voice.py) y el servidor manda en cada aviso la lista de piezas (`speechParts`).

Hasta $99,999.99. Un monto mayor (o una pieza que falte) se anuncia como antes: ElevenLabs en vivo
o la voz del teléfono, con el texto de `speech`.
"""

import json
from pathlib import Path

from num2words import num2words

from app import config, timeutil

MAX_PESOS = 99_999
VOICE_DIR = config.STATIC_DIR / "voice"

HUNDREDS = {1: "ciento", 2: "doscientos", 3: "trescientos", 4: "cuatrocientos", 5: "quinientos",
            6: "seiscientos", 7: "setecientos", 8: "ochocientos", 9: "novecientos"}


def _num(n: int) -> str:
    return num2words(n, lang="es")


def _apocope(n: int) -> str:
    """1 -> 'un', 21 -> 'veintiún', 31 -> 'treinta y un' (antes de 'pesos', 'centavos' o 'mil')."""
    return {1: "un", 21: "veintiún"}.get(n) or _num(n)[:-1]


def _catalog() -> dict[str, dict]:
    """Clave -> texto y contexto para generarlo (previous_text/next_text hacen que suene dentro de la frase)."""
    c: dict[str, dict] = {}

    def add(key, text, prev="", nxt=""):
        c[key] = {"text": text, "prev": prev, "next": nxt}

    add("recibiste", "Recibiste", "", "cincuenta pesos con veinte centavos.")
    add("simulacion", "Simulación.", "", "Recibiste cincuenta pesos.")
    add("peso", "peso", "Recibiste un", "con veinte centavos.")
    add("pesos", "pesos", "Recibiste cincuenta", "con veinte centavos.")
    # al final de la frase (sin centavos) la entonación baja
    add("peso_fin", "peso.", "Recibiste un", "")
    add("pesos_fin", "pesos.", "Recibiste cincuenta", "")
    add("con", "con", "Recibiste cincuenta pesos", "veinte centavos.")
    add("centavo", "centavo.", "Recibiste cincuenta pesos con un", "")
    add("centavos", "centavos.", "Recibiste cincuenta pesos con veinte", "")
    for n in range(1, 100):
        add(f"n{n}", _num(n), "Recibiste", "pesos.")
    for n in (1, 21, 31, 41, 51, 61, 71, 81, 91):
        add(f"u{n}", _apocope(n), "Recibiste", "pesos.")
    add("h100", "cien", "Recibiste", "pesos.")
    for h, word in HUNDREDS.items():
        add(f"h{h}", word, "Recibiste", "veinte pesos.")
    add("mil", "mil", "Recibiste dos", "quinientos pesos.")
    # Último pago y hora
    # Sin dos puntos: termina como frase abierta y se pega al número (los números empiezan "en seco" porque se
    # generaron como continuación de "Recibiste"; después de una pausa larga sonaban cortados)
    add("ultimo_pago", "Último pago", "", "cincuenta pesos, a las siete y media de la noche.")
    add("a_la_una", "a la una", "Último pago: cincuenta pesos,", "y veinte de la tarde.")
    for h in range(2, 13):
        add(f"a_las_{h}", f"a las {_num(h)}", "Último pago: cincuenta pesos,", "y veinte de la tarde.")
    add("y", "y", "a las siete", "treinta y tres de la noche.")
    add("en_punto", "en punto", "a las siete", "de la noche.")
    for key, part in (("de_la_manana", "mañana"), ("de_la_tarde", "tarde"), ("de_la_noche", "noche")):
        add(key, f"de la {part}.", "a las siete y veinte", "")
    # Avisos
    add("sin_conexion", "Sin conexión.")
    add("sin_pagos", "Todavía no hay pagos.")
    return c


CLIPS = _catalog()


def text_of(parts: list[str]) -> str:
    return " ".join(CLIPS[p]["text"] for p in parts)


# --- armar las frases ---------------------------------------------------------
def _below_1000(n: int, before_noun: bool) -> list[str]:
    """1..999 en piezas. before_noun: 'un'/'veintiún' en vez de 'uno'/'veintiuno'."""
    parts, h, r = [], n // 100, n % 100
    if h:
        parts.append("h100" if h == 1 and r == 0 else f"h{h}")
    if r:
        parts.append(f"u{r}" if before_noun and r % 10 == 1 and r != 11 else f"n{r}")
    return parts


def _number(n: int) -> list[str]:
    """1..99,999 antes de un sustantivo ('veintiún mil quinientos', 'mil un')."""
    thousands, rest = divmod(n, 1000)
    parts = []
    if thousands:
        parts += ([] if thousands == 1 else _below_1000(thousands, before_noun=True)) + ["mil"]
    if rest:
        parts += _below_1000(rest, before_noun=True)
    return parts


def money_parts(amount: float, final: bool = True) -> list[str] | None:
    """'cincuenta · pesos · con · veinte · centavos'. None si no se puede armar (0 o más de $99,999.99).
    final: la frase termina aquí (sin centavos, 'pesos.' con entonación de cierre)."""
    cents = round(float(amount) * 100)
    pesos, cent = divmod(cents, 100)
    if cents <= 0 or pesos > MAX_PESOS:
        return None
    parts = []
    if pesos:
        noun = "peso" if pesos == 1 else "pesos"
        parts += _number(pesos) + [f"{noun}_fin" if final and not cent else noun]
    if cent:
        parts += (["con"] if pesos else []) + _below_1000(cent, before_noun=True) + ["centavo" if cent == 1 else "centavos"]
    return parts


def payment_parts(amount: float, simulated: bool = False) -> list[str] | None:
    money = money_parts(amount)
    if money is None:
        return None
    return (["simulacion"] if simulated else []) + ["recibiste"] + money


def time_parts(ts: int) -> list[str]:
    """'a las siete · y · treinta y tres · de la noche' (misma regla que timeutil.spoken_time)."""
    t = timeutil.local(ts)
    h = t.hour % 12 or 12
    parts = ["a_la_una" if h == 1 else f"a_las_{h}"]
    parts += ["en_punto"] if t.minute == 0 else ["y", f"n{t.minute}"]
    parts.append("de_la_manana" if t.hour < 12 else "de_la_tarde" if t.hour < 19 else "de_la_noche")
    return parts


def last_payment_parts(amount: float, paid_at: int, simulated: bool = False) -> list[str] | None:
    money = money_parts(amount, final=False)  # sigue la hora
    if money is None:
        return None
    return (["simulacion"] if simulated else []) + ["ultimo_pago"] + money + time_parts(paid_at)


# --- qué hay generado -----------------------------------------------------------
def manifest_for(voice_id: str) -> dict | None:
    path = VOICE_DIR / voice_id / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def available(voice_id: str | None = None) -> bool:
    """¿Están todos los audios de la voz configurada? Si falta alguno, el navegador usa el respaldo."""
    m = manifest_for(voice_id or config.ELEVENLABS_VOICE_ID)
    return bool(m) and set(CLIPS) <= set((m.get("clips") or {}).keys())
