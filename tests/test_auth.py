"""Cuentas: registro con la CLABE en pey, entrar con PIN, separación entre negocios, activación, bocinas y demo."""

import pytest
from conftest import (DEMO_PHONE, DEMO_PIN, NOW, add_charge, add_merchant, count, demo_ids, payment, qr_payment, run,
                      sign_and_post)

from app import merchants, pey
from app.db import connect
from app.events import bus

BBVA = "012180001234567899"     # dígito verificador válido
BANORTE = "072180009999888871"
SIGNUP = {"phone": "55 1111 2222", "pin": "730146", "firstName": "Lupita", "lastName": "Pérez Ruiz",
          "businessName": "Tortas Lupita", "clabe": BBVA}


@pytest.fixture
def fake_pey(monkeypatch):
    calls = {"register": [], "qr": [], "push": [], "account": []}

    async def register(alias, name, clabe):
        calls["register"].append({"alias": alias, "name": name, "clabe": clabe})
        return {"id": f"BA_{clabe[-4:]}", "codiStatus": "PENDING"}

    async def create_qr(amount, concept, expiration, bank_account_id=None):
        calls["qr"].append({"amount": amount, "bank": bank_account_id})
        n = len(calls["qr"])
        return f"QR{n}", f"QRSTRING{n}", "1"

    async def push(amount, phone, concept, expiration, metadata, bank_account_id=None):
        calls["push"].append({"amount": amount, "bank": bank_account_id})
        return {"transactionId": f"PN{len(calls['push'])}", "codiId": "C1"}

    async def get_account(bank_account_id):
        calls["account"].append(bank_account_id)
        return {"id": bank_account_id, "codiStatus": calls.get("next_status", "PROCESSING")}

    monkeypatch.setattr(pey, "register_bank_account", register)
    monkeypatch.setattr(pey, "create_qr", create_qr)
    monkeypatch.setattr(pey, "push", push)
    monkeypatch.setattr(pey, "get_bank_account", get_account)
    return calls


def signup(c, **over):
    return c.post("/api/auth/signup", json={**SIGNUP, **over})


# --- registro ------------------------------------------------------------------
def test_signup_registers_the_clabe_in_pey_and_starts_pending(anon, fake_pey):
    r = signup(anon)

    assert r.status_code == 200, r.text
    assert fake_pey["register"] == [{"alias": "Tortas Lupita", "name": "Lupita Pérez Ruiz", "clabe": BBVA}]
    me = anon.get("/api/me").json()
    assert me["merchant"]["codiStatus"] == "PENDING" and me["merchant"]["businessName"] == "Tortas Lupita"
    assert me["merchant"]["bank"] == "BBVA" and me["merchant"]["depositAccount"] == "BBVA ···· 7899"
    assert me["user"] == {"firstName": "Lupita", "lastName": "Pérez Ruiz", "phone4": "2222"} and me["role"] == "owner"
    with connect() as conn:
        assert conn.execute("SELECT pin_hash FROM users WHERE phone='5511112222'").fetchone()[0].startswith("scrypt$")


def test_pending_account_cannot_charge(anon, fake_pey):
    """Sin cuenta activa el dinero caería en la cuenta de la API key: no se permite cobrar."""
    signup(anon)
    for url, body in (("/api/charges", {"amount": 10}), ("/api/push", {"amount": 10, "phone": "5512345678"})):
        r = anon.post(url, json=body)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_active"
    assert fake_pey["qr"] == [] and fake_pey["push"] == []
    assert anon.get("/api/fixed-qr").json() == {"fixed": None}


@pytest.mark.parametrize("over, code", [
    ({"clabe": "012180001234567890"}, "bad_clabe"),   # dígito verificador incorrecto
    ({"clabe": "1234"}, "bad_clabe"),
    ({"pin": "123456"}, "bad_pin"),
    ({"pin": "111111"}, "bad_pin"),
    ({"pin": "12345"}, "bad_pin"),
    ({"phone": "555"}, "bad_phone"),
    ({"firstName": " "}, "bad_name"),
    ({"businessName": ""}, "bad_business"),
])
def test_signup_validation(anon, fake_pey, over, code):
    r = signup(anon, **over)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code
    assert fake_pey["register"] == []


def test_signup_with_taken_phone_or_clabe(anon, fake_pey):
    assert signup(anon).status_code == 200
    r = signup(anon, clabe=BANORTE)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "phone_taken"
    r = signup(anon, phone="5533334444")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "clabe_taken"


def test_pey_rejecting_the_clabe_creates_nothing(anon, monkeypatch):
    async def reject(alias, name, clabe):
        raise pey.PeyError(422, "bad_clabe", "pey no aceptó esa CLABE.")
    monkeypatch.setattr(pey, "register_bank_account", reject)

    r = signup(anon)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_clabe"
    assert count("users") == 1 and count("merchants") == 1  # solo la demo


# --- entrar / salir ------------------------------------------------------------
def test_login_and_logout(anon):
    assert anon.get("/api/me").status_code == 401
    assert anon.post("/api/auth/login", json={"phone": DEMO_PHONE, "pin": DEMO_PIN}).status_code == 200
    assert anon.get("/api/me").json()["merchant"]["isDemo"] is True
    anon.post("/api/auth/logout")
    assert anon.get("/api/me").status_code == 401


def test_wrong_pin_locks_the_phone_after_five_tries(anon):
    for _ in range(5):
        r = anon.post("/api/auth/login", json={"phone": DEMO_PHONE, "pin": "000001"})
        assert r.status_code == 401
    r = anon.post("/api/auth/login", json={"phone": DEMO_PHONE, "pin": DEMO_PIN})  # ni con el PIN correcto
    assert r.status_code == 429 and r.json()["detail"]["code"] == "locked"


def test_lock_expires_after_15_minutes(anon, clock):
    for _ in range(5):
        anon.post("/api/auth/login", json={"phone": DEMO_PHONE, "pin": "000001"})
    clock.now += 15 * 60 + 1
    assert anon.post("/api/auth/login", json={"phone": DEMO_PHONE, "pin": DEMO_PIN}).status_code == 200


def test_session_expires(client, clock):
    clock.now += 91 * 86400
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("method, url", [
    ("get", "/api/payments"), ("get", "/api/fixed-qr"), ("get", "/api/last-payment"), ("get", "/api/events"),
    ("post", "/api/charges"), ("post", "/api/push"), ("post", "/api/tts"), ("post", "/api/assistant"),
])
def test_everything_needs_a_session(anon, method, url):
    r = getattr(anon, method)(url, json={}) if method == "post" else anon.get(url)
    assert r.status_code == 401


def test_status_is_public_and_shows_demo_credentials(anon):
    st = anon.get("/api/status").json()
    assert st["demo"]["phone"] == DEMO_PHONE and st["demo"]["pin"] == DEMO_PIN


# --- negocios separados --------------------------------------------------------
def test_merchants_only_see_their_own_payments(client, anon, events):
    add_charge("QRFIJO", kind="fixed")
    lupita = add_merchant(phone="5511112222", bank_account_id="BA_LUPITA")
    add_charge("QRLUPITA", kind="fixed", merchant=lupita)
    lupita_q = bus.subscribe(lupita[0])

    sign_and_post(client, qr_payment("TX_RAMON", 10), webhook_id="m1")
    sign_and_post(client, qr_payment("TX_LUPITA", 99, qr_id="QRLUPITA"), webhook_id="m2")

    assert [e["transactionId"] for e in events()] == ["TX_RAMON"]   # la bocina de Ramón no oye a Lupita
    assert lupita_q.get_nowait()["transactionId"] == "TX_LUPITA" and lupita_q.empty()
    assert [p["transactionId"] for p in client.get("/api/payments").json()["payments"]] == ["TX_RAMON"]
    anon.post("/api/auth/login", json={"phone": "5511112222", "pin": "730146"})
    assert [p["transactionId"] for p in anon.get("/api/payments").json()["payments"]] == ["TX_LUPITA"]


def test_unknown_qr_with_bank_account_goes_to_that_merchant(client):
    mid, _ = add_merchant(phone="5511112222", bank_account_id="BA_LUPITA")
    sign_and_post(client, qr_payment("TX1", 20, qr_id="IMPRESO_VIEJO", bankAccountId="BA_LUPITA"))
    assert payment("TX1")["merchant_id"] == mid and payment("TX1")["kind"] == "external"


def test_cannot_touch_another_merchants_charge(client):
    lupita = add_merchant(phone="5511112222")
    add_charge("PN_LUPITA", kind="push", amount=40, merchant=lupita)
    client.post("/api/push/PN_LUPITA/dismiss")  # Ramón intenta quitar el cobro de Lupita
    with connect() as conn:
        assert conn.execute("SELECT status FROM charges WHERE id='PN_LUPITA'").fetchone()[0] == "pending"


# --- activación en CoDi ----------------------------------------------------------
def test_activation_webhook_creates_the_fixed_qr_on_the_merchants_clabe(client, anon, fake_pey):
    signup(anon)
    mid = anon.get("/api/me").json()["merchant"]["id"]
    q = bus.subscribe(mid)

    r = sign_and_post(client, {"type": "bank.account.updated", "bankAccountId": "BA_7899", "codiStatus": "ACTIVE",
                               "clabe": BBVA, "entity": "PERSON", "name": "Lupita Pérez Ruiz"}, webhook_id="ba1")

    assert r.json() == {"ok": True}
    assert fake_pey["qr"] == [{"amount": 0, "bank": "BA_7899"}]
    assert anon.get("/api/me").json()["merchant"]["codiStatus"] == "ACTIVE"
    assert anon.get("/api/fixed-qr").json()["fixed"]["id"] == "QR1"
    assert [q.get_nowait()["type"] for _ in range(2)] == ["account", "fixed"]

    # ya puede cobrar, siempre a su CLABE
    anon.post("/api/charges", json={"amount": 80})
    anon.post("/api/push", json={"amount": 80, "phone": "5512345678"})
    assert fake_pey["qr"][-1]["bank"] == "BA_7899" and fake_pey["push"] == [{"amount": 80, "bank": "BA_7899"}]


def test_app_checks_pey_while_pending_as_a_backup(anon, fake_pey, clock):
    signup(anon)
    anon.get("/api/me")
    assert fake_pey["account"] == []        # recién registrada: no se consulta todavía
    clock.now += 61
    fake_pey["next_status"] = "ACTIVE"
    me = anon.get("/api/me").json()
    assert fake_pey["account"] == ["BA_7899"] and me["merchant"]["codiStatus"] == "ACTIVE"
    assert anon.get("/api/fixed-qr").json()["fixed"]["id"] == "QR1"


def test_rejected_clabe_can_be_corrected(anon, fake_pey, clock):
    signup(anon)
    with connect() as conn:
        conn.execute("UPDATE merchants SET codi_status='ERROR', codi_error='CLABE no registrada en CoDi'")
    r = anon.post("/api/account/bank", json={"firstName": "Lupita", "lastName": "Pérez", "clabe": BANORTE})
    assert r.status_code == 200, r.text
    m = anon.get("/api/me").json()["merchant"]
    assert m["codiStatus"] == "PENDING" and m["bank"] == "Banorte" and m["codiError"] is None


# --- bocina vinculada ------------------------------------------------------------
def test_speaker_pairing(client, anon):
    add_charge("QRFIJO", kind="fixed")
    code = anon.post("/api/devices/pair").json()["code"]
    assert anon.get("/api/devices/pair").json()["paired"] is False
    assert anon.get("/api/fixed-qr").status_code == 401

    assert client.post("/api/devices/claim", json={"code": code}).status_code == 200
    assert anon.get("/api/devices/pair").json() == {"paired": True}

    me = anon.get("/api/me").json()
    assert me["device"] is True and me["merchant"]["businessName"] == "Abarrotes Ramón" and "user" not in me
    assert anon.get("/api/fixed-qr").json()["fixed"]["id"] == "QRFIJO"
    assert anon.get("/api/last-payment").status_code == 200
    # una bocina no cobra ni ve el historial completo
    assert anon.get("/api/payments").status_code == 403
    assert anon.post("/api/charges", json={"amount": 10}).status_code == 403
    # y la bocina puede desvincularse
    anon.post("/api/devices/forget")
    assert anon.get("/api/me").status_code == 401


def test_wrong_or_used_pair_code(client, anon):
    assert client.post("/api/devices/claim", json={"code": "000000"}).status_code == 404
    code = anon.post("/api/devices/pair").json()["code"]
    client.post("/api/devices/claim", json={"code": code})
    assert client.post("/api/devices/claim", json={"code": code}).status_code == 404


def test_pair_code_expires(anon, clock):
    anon.post("/api/devices/pair")
    clock.now += 11 * 60
    assert anon.get("/api/devices/pair").status_code == 410


# --- cuenta demo -----------------------------------------------------------------
def test_demo_push_limits(client, anon, fake_pey):
    over = client.post("/api/push", json={"amount": 51, "phone": "5512345678"})
    assert over.status_code == 422 and over.json()["detail"]["code"] == "demo_limit"
    for _ in range(3):
        assert client.post("/api/push", json={"amount": 20, "phone": "5512345678"}).status_code == 200
    fourth = client.post("/api/push", json={"amount": 20, "phone": "5512345678"})
    assert fourth.status_code == 429 and fourth.json()["detail"]["code"] == "demo_limit"
    assert client.get("/api/me").json()["demoPush"]["session"] == 0
    # otra persona (otra sesión) todavía puede
    anon.post("/api/auth/login", json={"phone": DEMO_PHONE, "pin": DEMO_PIN})
    assert anon.post("/api/push", json={"amount": 20, "phone": "5512345678"}).status_code == 200
    assert fake_pey["push"][0]["bank"] is None  # la demo cobra en la cuenta de la API key


def test_demo_daily_push_limit(client, fake_pey, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEMO_PUSH_PER_DAY", 2)
    monkeypatch.setattr(config, "DEMO_PUSH_PER_SESSION", 10)
    for _ in range(2):
        client.post("/api/push", json={"amount": 5, "phone": "5512345678"})
    r = client.post("/api/push", json={"amount": 5, "phone": "5512345678"})
    assert r.status_code == 429 and "hoy" in r.json()["detail"]["message"]


def test_real_merchant_has_no_push_limit(anon, fake_pey):
    add_merchant(phone="5511112222", bank_account_id="BA_LUPITA")
    anon.post("/api/auth/login", json={"phone": "5511112222", "pin": "730146"})
    for _ in range(5):
        assert anon.post("/api/push", json={"amount": 500, "phone": "5512345678"}).status_code == 200


def test_demo_cannot_replace_its_fixed_qr(client, fake_pey):
    r = client.post("/api/fixed-qr", json={"name": "Otro"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "demo_locked"


def test_old_data_belongs_to_the_demo(tmp_path, monkeypatch, clock):
    """Al arrancar, los cobros y pagos de antes de las cuentas pasan a la demo."""
    import sqlite3

    from fastapi.testclient import TestClient

    from app import config
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE charges (id TEXT PRIMARY KEY, amount REAL NOT NULL, concept TEXT NOT NULL, num_ref TEXT NOT NULL,"
        " status TEXT NOT NULL, created_at INTEGER NOT NULL, expiration INTEGER NOT NULL, paid_at INTEGER, paid_amount REAL,"
        " transaction_id TEXT, simulated INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'amount', qr_string TEXT);"
        "INSERT INTO charges VALUES ('OLDQR', 0, 'Mi tienda', '0', 'active', 1, 0, NULL, NULL, NULL, 0, 'fixed', 'S');"
        "CREATE TABLE payments (transaction_id TEXT PRIMARY KEY, codi_qr_id TEXT, kind TEXT, amount REAL NOT NULL,"
        " concept TEXT, paid_at INTEGER NOT NULL, simulated INTEGER NOT NULL DEFAULT 0);"
        f"INSERT INTO payments VALUES ('OLDTX', 'OLDQR', 'fixed', 12.5, '', {NOW}, 0);"
    )
    conn.commit(); conn.close()
    for k, v in {"DB_PATH": str(db), "DEMO_PHONE": DEMO_PHONE, "DEMO_PIN": DEMO_PIN, "PEY_API_KEY": "",
                 "RECOVERY_POLL_SECONDS": 0}.items():
        monkeypatch.setattr(config, k, v)
    from app.main import app
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"phone": DEMO_PHONE, "pin": DEMO_PIN})
        assert [p["transactionId"] for p in c.get("/api/payments").json()["payments"]] == ["OLDTX"]
        assert c.get("/api/fixed-qr").json()["fixed"]["id"] == "OLDQR"
    bus.subs.clear()


def test_clabe_check_digit():
    assert merchants.clabe_problem("032180000118359719") is None  # ejemplo de Banxico
    assert merchants.clabe_problem("032180000118359718")
    assert merchants.bank_for_clabe(BANORTE) == "Banorte"
