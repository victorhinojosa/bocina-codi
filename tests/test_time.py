"""Horas en la zona del negocio. Caso real: un pago de las 7:33 pm se decía 'a la 1:33 de la mañana'."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from conftest import add_charge, qr_payment, sign_and_post

from app import timeutil

MX = ZoneInfo("America/Mexico_City")


def mx(*args) -> int:
    return int(datetime(*args, tzinfo=MX).timestamp())


@pytest.fixture(autouse=True)
def mexico_tz(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "BUSINESS_TZ", "America/Mexico_City")


def test_reported_case_is_said_in_mexico_city_time():
    ts = mx(2026, 11, 24, 19, 33)  # = 01:33 UTC del día 25
    assert timeutil.spoken_time(ts) == "a las siete y treinta y tres de la noche"


@pytest.mark.parametrize("hm, expected", [
    ((13, 33), "a la una y treinta y tres de la tarde"),
    ((1, 5), "a la una y cinco de la mañana"),
    ((0, 0), "a las doce en punto de la mañana"),
    ((12, 21), "a las doce y veintiuno de la tarde"),
    ((9, 0), "a las nueve en punto de la mañana"),
    ((21, 45), "a las nueve y cuarenta y cinco de la noche"),
])
def test_spoken_time_wording(hm, expected):
    assert timeutil.spoken_time(mx(2026, 11, 24, *hm)) == expected


def test_spoken_time_has_no_digits_for_the_voice():
    for h in range(24):
        assert not any(ch.isdigit() for ch in timeutil.spoken_time(mx(2026, 11, 24, h, 7)))


def test_start_of_day_uses_business_timezone():
    late_evening = mx(2026, 11, 24, 21, 0)  # en UTC ya es 25
    assert timeutil.start_of_day(now=late_evening) == mx(2026, 11, 24, 0, 0)
    assert timeutil.start_of_day(1, now=late_evening) == mx(2026, 11, 23, 0, 0)


@pytest.mark.parametrize("raw, expected", [(1795570408, 1795570408), (1795570408123, 1795570408),
                                           ("1795570408", 1795570408), (None, None), ("x", None), (0, None)])
def test_to_seconds(raw, expected):
    assert timeutil.to_seconds(raw) == expected


def test_last_payment_speech_uses_local_hour(client, clock):
    add_charge("QRFIJO", kind="fixed")
    paid = mx(2026, 11, 24, 19, 33)
    clock.now = paid + 3
    sign_and_post(client, qr_payment("TX1", 100, paid_at=paid))

    speech = client.get("/api/last-payment").json()["speech"]
    assert speech == "Último pago: 100 pesos, a las siete y treinta y tres de la noche."


def test_evening_payment_counts_for_today_not_tomorrow(client, clock):
    """Con el servidor en UTC, después de las 6 pm 'hoy' ya era mañana y el total se reiniciaba."""
    add_charge("QRFIJO", kind="fixed")
    clock.now = mx(2026, 11, 24, 17, 0)
    sign_and_post(client, qr_payment("A", 10, paid_at=clock.now), webhook_id="m1")
    clock.now = mx(2026, 11, 24, 20, 0)
    sign_and_post(client, qr_payment("B", 20, paid_at=clock.now), webhook_id="m2")

    s = client.get("/api/payments").json()
    assert s["todayTotal"] == 30 and s["todayCount"] == 2

    clock.now = mx(2026, 11, 25, 8, 0)
    s = client.get("/api/payments").json()
    assert s["todayTotal"] == 0 and s["yesterdayTotal"] == 30
