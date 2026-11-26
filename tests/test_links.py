"""Link de pago: crear, recibir el pago por webhook o respaldo, y quién puede usarlo."""

import pytest
from conftest import NOW, add_merchant, count, payment, run, sign_and_post

from app import config, pey
from app.db import connect
from app.recovery import recovery

HTTPS = {"x-forwarded-proto": "https", "host": "din.example.com"}


@pytest.fixture
def fake_link(monkeypatch):
    calls = []

    async def create(amount, success_url, back_url, reference, metadata):
        calls.append({"amount": amount, "success": success_url, "back": back_url, "ref": reference, "meta": metadata})
        return {"id": f"PL{len(calls)}", "url": f"https://pay.pey.mx/l/PL{len(calls)}"}

    monkeypatch.setattr(pey, "create_payment_link", create)
    return calls


def tx(tid, base=120.0, tip=0.0, fee=4.5, method="CARD", paid=NOW):
    return {"transactionId": tid, "paymentMethod": method, "datePaid": paid, "amount": base + tip + fee,
            "amountBreakdown": {"base": base, "tip": tip, "fee": fee}, "applicationFee": 3.0, "metadata": {}}


def make_link(client, amount=120, concept="Pastel"):
    r = client.post("/api/links", json={"amount": amount, "concept": concept}, headers=HTTPS)
    assert r.status_code == 200, r.text
    return r.json()


def test_demo_creates_a_link_with_return_pages(client, fake_link):
    x = make_link(client)
    assert x["url"] == "https://pay.pey.mx/l/PL1" and x["kind"] == "link" and x["amount"] == 120
    c = fake_link[0]
    assert c["success"] == "https://din.example.com/pago/listo" and c["back"] == "https://din.example.com/pago/cancelado"
    pend = client.get("/api/payments").json()["pending"]
    assert [(p["id"], p["kind"], p["url"]) for p in pend] == [("PL1", "link", "https://pay.pey.mx/l/PL1")]
    assert client.get("/api/me").json()["merchant"]["linksEnabled"] is True


def test_link_needs_https(client, fake_link):
    r = client.post("/api/links", json={"amount": 10})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "needs_https" and fake_link == []


def test_public_url_overrides_the_host(client, fake_link, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://abc.ngrok.app/")
    client.post("/api/links", json={"amount": 10})
    assert fake_link[0]["success"] == "https://abc.ngrok.app/pago/listo"


def test_merchant_with_own_clabe_cannot_use_links(anon, fake_link):
    """pey no deja elegir la cuenta del link: el dinero caería en la cuenta de la API key, no en la del negocio."""
    add_merchant(phone="5511112222", bank_account_id="BA_LUPITA")
    anon.post("/api/auth/login", json={"phone": "5511112222", "pin": "730146"})
    r = anon.post("/api/links", json={"amount": 10}, headers=HTTPS)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "link_unavailable" and fake_link == []
    assert anon.get("/api/me").json()["merchant"]["linksEnabled"] is False


def test_link_paid_by_card_via_webhook(client, fake_link, events):
    make_link(client)
    events()
    r = sign_and_post(client, {"type": "payment_link.status_updated", "paymentLinkId": "PL1", "status": "PAID",
                               "remainingAmount": 0, "transactions": [tx("TXL1", base=120, tip=10)]})
    assert r.json() == {"ok": True}
    p = payment("TXL1")
    assert p["kind"] == "link" and p["method"] == "CARD" and p["amount"] == 130  # base + propina; la comisión no es del negocio
    assert p["expected_amount"] == 120
    [e] = events()
    assert e["type"] == "payment" and e["kind"] == "link" and e["chargeId"] == "PL1" and e["speech"] == "Recibiste 130 pesos"
    assert client.get("/api/payments").json()["pending"] == []  # ya no está pendiente
    with connect() as conn:
        assert conn.execute("SELECT status FROM charges WHERE id='PL1'").fetchone()[0] == "paid"


def test_processing_status_only_refreshes(client, fake_link, events):
    make_link(client)
    events()
    sign_and_post(client, {"type": "payment_link.status_updated", "paymentLinkId": "PL1", "status": "PROCESSING",
                           "transactions": []})
    assert [e["type"] for e in events()] == ["pending"] and count("payments") == 0


def test_link_payment_recovered_when_webhook_is_lost(client, fake_link, monkeypatch, events):
    make_link(client)
    events()

    async def get_link(c, link_id):
        return {"id": link_id, "status": "PAID", "transactions": [tx("TXL2", base=120, method="CODI")]}

    async def nothing(*a, **kw):
        return {"items": [], "nextToken": None}

    monkeypatch.setattr(pey, "get_payment_link", get_link)
    monkeypatch.setattr(pey, "list_qr_transactions", nothing)
    assert run(recovery.poll_once()) == 1
    assert payment("TXL2")["source"] == "recovery" and payment("TXL2")["kind"] == "link"
    # y el webhook que llega después no lo repite
    sign_and_post(client, {"type": "payment_link.status_updated", "paymentLinkId": "PL1", "status": "PAID",
                           "transactions": [tx("TXL2", base=120, method="CODI")]})
    assert count("payments") == 1 and len([e for e in events() if e["type"] == "payment"]) == 1


def test_dismiss_link(client, fake_link):
    make_link(client)
    client.post("/api/links/PL1/dismiss")
    assert client.get("/api/payments").json()["pending"] == []


def test_return_pages(anon):
    assert "Gracias" in anon.get("/pago/listo").text
    assert "No se hizo el pago" in anon.get("/pago/cancelado").text
