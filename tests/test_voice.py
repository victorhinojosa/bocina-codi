"""Voz pregenerada: las piezas arman exactamente la frase correcta, y el generador no repite trabajo."""

import importlib
import json
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from conftest import NOW, add_charge, qr_payment, sign_and_post

from app import config, timeutil, voice
from app.speech import amount_letters

MX = ZoneInfo("America/Mexico_City")


def said(parts) -> str:
    return voice.text_of(parts).replace(".", "").replace(":", "").lower()


def expected(amount) -> str:
    return amount_letters(amount).lower()


@pytest.fixture(autouse=True)
def mexico(monkeypatch):
    monkeypatch.setattr(config, "BUSINESS_TZ", "America/Mexico_City")


def test_every_whole_peso_amount_up_to_99999():
    for pesos in range(1, voice.MAX_PESOS + 1):
        assert said(voice.money_parts(pesos)) == expected(pesos), pesos


def test_every_cents_value_and_random_mixed_amounts():
    for cents in range(1, 100):
        a = cents / 100
        assert said(voice.money_parts(a)) == expected(a), a
    rnd = random.Random(7)
    for _ in range(5000):
        a = round(rnd.randint(1, voice.MAX_PESOS) + rnd.randint(0, 99) / 100, 2)
        assert said(voice.money_parts(a)) == expected(a), a


@pytest.mark.parametrize("amount, text", [
    (50.20, "Recibiste cincuenta pesos con veinte centavos."),
    (1, "Recibiste un peso."),
    (21, "Recibiste veintiún pesos."),
    (21500, "Recibiste veintiún mil quinientos pesos."),
    (1001, "Recibiste mil un pesos."),
    (101, "Recibiste ciento un pesos."),
    (0.01, "Recibiste un centavo."),
])
def test_examples(amount, text):
    assert voice.text_of(voice.payment_parts(amount)) == text


def test_out_of_range_falls_back():
    assert voice.payment_parts(100_000) is None and voice.payment_parts(0) is None


def test_simulation_prefix():
    assert voice.payment_parts(5, simulated=True)[:2] == ["simulacion", "recibiste"]


def test_time_matches_spoken_time_for_every_minute():
    for minute in range(24 * 60):
        ts = int(datetime(2026, 11, 24, minute // 60, minute % 60, tzinfo=MX).timestamp())
        assert voice.text_of(voice.time_parts(ts)).rstrip(".") == timeutil.spoken_time(ts), minute


def test_last_payment_parts_keep_pesos_mid_sentence():
    ts = int(datetime(2026, 11, 24, 19, 33, tzinfo=MX).timestamp())
    parts = voice.last_payment_parts(50, ts)
    assert voice.text_of(parts) == "Último pago cincuenta pesos a las siete y treinta y tres de la noche."


def test_all_parts_exist_in_the_catalog():
    for a in (0.01, 1, 21.21, 99999.99, 345.5):
        assert set(voice.payment_parts(a)) <= set(voice.CLIPS)


def test_payment_event_and_last_payment_carry_parts(client, events, clock):
    add_charge("QRFIJO", kind="fixed")
    sign_and_post(client, qr_payment("TX1", 50.2))
    [e] = events()
    assert e["speechParts"] == ["recibiste", "n50", "pesos", "con", "n20", "centavos"]
    last = client.get("/api/last-payment").json()
    assert last["speechParts"][:3] == ["ultimo_pago", "n50", "pesos"]


def test_status_reports_clips_only_when_complete(client, tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "VOICE_DIR", tmp_path)
    assert client.get("/api/status").json()["voice"]["clips"] is False
    folder = tmp_path / config.ELEVENLABS_VOICE_ID
    folder.mkdir()
    clips = {k: {"file": f"{k}.mp3", "hash": "x"} for k in voice.CLIPS}
    (folder / "manifest.json").write_text(json.dumps({"clips": clips}), encoding="utf-8")
    assert client.get("/api/status").json()["voice"]["clips"] is True
    del clips["n35"]
    (folder / "manifest.json").write_text(json.dumps({"clips": clips}), encoding="utf-8")
    assert client.get("/api/status").json()["voice"]["clips"] is False


def test_generator_creates_everything_once(tmp_path, monkeypatch):
    gen = importlib.import_module("scripts.generate_voice")
    monkeypatch.setattr(gen, "VOICE_DIR", tmp_path)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, content=b"ID3" + body["text"].encode())

    real_client = httpx.Client
    monkeypatch.setattr(gen.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr("sys.argv", ["generate_voice.py", "--voice", "VOZTEST"])
    assert gen.main() == 0
    assert len(sent) == len(voice.CLIPS)
    assert all(b["model_id"] == "eleven_multilingual_v2" for b in sent)
    assert next(b for b in sent if b["text"] == "cincuenta")["previous_text"] == "Recibiste"
    manifest = json.loads((tmp_path / "VOZTEST" / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["clips"]) == set(voice.CLIPS)
    assert manifest["clips"]["con"]["file"] == "_con.mp3"  # "con" es un nombre reservado en Windows
    # segunda vuelta: no genera nada
    sent.clear()
    assert gen.main() == 0 and sent == []
