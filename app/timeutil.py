"""Horas en la zona del negocio.

pey manda `datePaid` en segundos Unix (un instante, sin zona). Al convertirlo a "hora del reloj" hay que usar
la zona del negocio: el servidor en Railway corre en UTC, y con `time.localtime()` un pago de las 7:33 pm
en la Ciudad de México se decía "a la 1:33 de la mañana".
"""

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from num2words import num2words

from app import config


def tz() -> ZoneInfo:
    return ZoneInfo(config.BUSINESS_TZ)


def now_ts() -> int:
    return int(time.time())


def local(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz())


def to_seconds(ts) -> int | None:
    """Acepta segundos (lo documentado por pey) y por si acaso milisegundos. None si no es un número."""
    try:
        v = float(ts)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v > 1e11:  # 13 dígitos = milisegundos
        v /= 1000
    return int(v)


def start_of_day(days_ago: int = 0, now: int | None = None) -> int:
    """Medianoche (en la zona del negocio) de hoy, o de hace `days_ago` días."""
    d = local(now_ts() if now is None else now).date() - timedelta(days=days_ago)
    return int(datetime(d.year, d.month, d.day, tzinfo=tz()).timestamp())


def hhmm(ts: int) -> str:
    return local(ts).strftime("%H:%M")


def clock_now() -> str:
    return hhmm(now_ts())


def spoken_time(ts: int) -> str:
    """'a la una y treinta y tres de la tarde', 'a las siete en punto de la noche'.
    En palabras para que la voz no lea '1:33' como 'uno con treinta y tres'."""
    t = local(ts)
    h = t.hour % 12 or 12
    hour = "la una" if h == 1 else f"las {num2words(h, lang='es')}"
    minutes = "en punto" if t.minute == 0 else f"y {num2words(t.minute, lang='es')}"
    part = "de la mañana" if t.hour < 12 else "de la tarde" if t.hour < 19 else "de la noche"
    return f"a {hour} {minutes} {part}"
