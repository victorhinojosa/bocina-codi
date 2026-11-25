"""Respaldo del webhook: recuperar pagos que no llegaron, sin duplicar ni anunciar dos veces."""

import asyncio

import pytest
from conftest import NOW, add_charge, add_merchant, count, demo_ids, payment, qr_payment, run, sign_and_post

from app import config, pey
from app.db import connect
from app.events import bus
from app.recovery import Recovery, recovery


def pey_item(tx_id: str, amount: float, paid_at: int) -> dict:
    """Forma real de un item de GET /transaction/codi/qr/{id} (verificada contra pey)."""
    return {"id": tx_id, "status": "PAID", "amount": amount, "amountBreakdown": {"base": amount}, "currency": "MXN",
            "paymentMethod": "CODI", "description": "Mi tienda", "dateCreated": paid_at, "datePaid": paid_at,
            "metadata": {"bankCode": 40014, "clabe": "***6460", "trackingKey": "TRK" + tx_id}}


@pytest.fixture
def fake_pey(monkeypatch):
    """pey falso: pages[qr_id] = lista de páginas; txs[id] = transacción."""
    state = {"pages": {}, "txs": {}, "calls": []}

    async def list_qr(client, qr_id, token=None):
        state["calls"].append(("list", qr_id, token))
        pages = state["pages"].get(qr_id, [[]])
        i = int(token or 0)
        return {"items": pages[i], "nextToken": str(i + 1) if i + 1 < len(pages) else None}

    async def get_tx(client, tx_id):
        state["calls"].append(("get", tx_id))
        return state["txs"][tx_id]

    monkeypatch.setattr(pey, "list_qr_transactions", list_qr)
    monkeypatch.setattr(pey, "get_transaction", get_tx)
    return state


def test_missing_recent_payment_is_recovered_and_announced(client, events, fake_pey, clock):
    add_charge("QRFIJO", kind="fixed")
    fake_pey["pages"]["QRFIJO"] = [[pey_item("TX1", 25, NOW - 30)]]

    assert run(recovery.poll_once()) == 1

    p = payment("TX1")
    assert p["source"] == "recovery" and p["received_at"] is None and p["paid_at"] == NOW - 30
    assert p["kind"] == "fixed" and p["tracking_key"] == "TRKTX1"
    [e] = events()
    assert e["type"] == "payment" and e["announced"] and e["recovered"]


def test_old_recovered_payment_goes_to_history_without_announcing(client, events, fake_pey):
    add_charge("QRFIJO", kind="fixed")
    fake_pey["pages"]["QRFIJO"] = [[pey_item("TX1", 25, NOW - 600)]]

    run(recovery.poll_once())

    assert payment("TX1")["source"] == "recovery"
    [e] = events()
    assert e["type"] == "history" and not e["announced"]
    [h] = client.get("/api/payments").json()["payments"]
    assert h["recovered"] and h["receivedAt"] is None


def test_known_payments_are_skipped(client, events, fake_pey):
    add_charge("QRFIJO", kind="fixed")
    sign_and_post(client, qr_payment("TX1", 25))
    events()
    fake_pey["pages"]["QRFIJO"] = [[pey_item("TX1", 25, NOW)]]

    assert run(recovery.poll_once()) == 0
    assert count("payments") == 1 and events() == []
    assert payment("TX1")["source"] == "webhook"


def test_webhook_arriving_after_recovery_is_not_announced_again(client, events, fake_pey, clock):
    add_charge("QRFIJO", kind="fixed")
    fake_pey["pages"]["QRFIJO"] = [[pey_item("TX1", 25, NOW - 20)]]
    run(recovery.poll_once())
    assert len(events()) == 1

    clock.now = NOW + 40
    r = sign_and_post(client, qr_payment("TX1", 25, paid_at=NOW - 20))

    assert r.json() == {"ok": True}
    assert events() == []  # no se repite el anuncio
    p = payment("TX1")
    assert p["source"] == "recovery" and p["received_at"] == NOW + 40 and count("payments") == 1


def test_two_real_payments_in_the_same_second_are_both_kept(client, fake_pey):
    """Pasó en datos reales de pey: dos pagos de $0.01 al QR fijo en el mismo segundo, con ids distintos."""
    add_charge("QRFIJO", kind="fixed")
    fake_pey["pages"]["QRFIJO"] = [[pey_item("TXA", 0.01, NOW), pey_item("TXB", 0.01, NOW)]]
    assert run(recovery.poll_once()) == 2


def test_paging_stops_at_the_first_known_payment(client, fake_pey):
    add_charge("QRFIJO", kind="fixed")
    sign_and_post(client, qr_payment("OLD", 10, paid_at=NOW - 900))
    fake_pey["pages"]["QRFIJO"] = [
        [pey_item("NEW1", 1, NOW - 10)],
        [pey_item("NEW2", 2, NOW - 20), pey_item("OLD", 10, NOW - 900)],
        [pey_item("ANCIENT", 3, NOW - 5000)],
    ]

    assert run(recovery.poll_once()) == 2
    assert [c[2] for c in fake_pey["calls"] if c[0] == "list"] == [None, "1"]
    assert payment("ANCIENT") is None


def test_pending_amount_qr_and_push_are_recovered(client, events, fake_pey):
    add_charge("QR90", kind="amount", amount=90)
    add_charge("PUSH1", kind="push", amount=40, phone="5512345678")
    fake_pey["pages"]["QR90"] = [[pey_item("TXQ", 90, NOW - 5)]]
    fake_pey["txs"]["PUSH1"] = {"id": "PUSH1", "status": "PAID", "amount": 40, "datePaid": NOW - 5,
                                "payableType": "API_CODI_PN", "metadata": {}}

    assert run(recovery.poll_once()) == 2

    with connect() as conn:
        statuses = dict(conn.execute("SELECT id, status FROM charges").fetchall())
    assert statuses == {"QR90": "paid", "PUSH1": "paid"}
    assert payment("PUSH1")["kind"] == "push" and payment("PUSH1")["phone4"] == "5678"


def test_unpaid_push_is_left_pending(client, fake_pey):
    add_charge("PUSH1", kind="push", amount=40)
    fake_pey["txs"]["PUSH1"] = {"id": "PUSH1", "status": "PENDING", "amount": 40}
    assert run(recovery.poll_once()) == 0
    assert count("payments") == 0


def test_paid_and_old_charges_are_not_polled(client, fake_pey, clock):
    add_charge("QRFIJO", kind="fixed")
    add_charge("PAID", kind="amount", amount=5, status="paid")
    add_charge("STALE", kind="amount", amount=5, created_at=NOW - 2 * 86400)
    run(recovery.poll_once())
    assert {c[1] for c in fake_pey["calls"]} == {"QRFIJO"}


def test_one_failing_qr_does_not_stop_the_others(client, fake_pey, monkeypatch):
    import httpx
    add_charge("QRFIJO", kind="fixed")
    add_charge("QR90", kind="amount", amount=90)
    fake_pey["pages"]["QR90"] = [[pey_item("TXQ", 90, NOW)]]
    original = pey.list_qr_transactions

    async def flaky(client, qr_id, token=None):
        if qr_id == "QRFIJO":
            raise httpx.HTTPStatusError("429", request=httpx.Request("GET", "http://x"), response=httpx.Response(429))
        return await original(client, qr_id, token)

    monkeypatch.setattr(pey, "list_qr_transactions", flaky)
    assert run(recovery.poll_once()) == 1


def test_reconnecting_screen_triggers_recovery(client, monkeypatch):
    """Cada vez que una pantalla abre (o reabre) /api/events se pide una consulta inmediata."""
    from app.routes import history
    kicks = []
    monkeypatch.setattr(history.recovery, "kick", lambda: kicks.append(1))

    class FakeRequest:
        async def is_disconnected(self):
            return True

    from app.auth import Viewer
    with connect() as conn:
        m = conn.execute("SELECT * FROM merchants WHERE is_demo=1").fetchone()
        st = conn.execute("SELECT * FROM stores WHERE merchant_id=?", (m["id"],)).fetchone()
    resp = run(history.events(FakeRequest(), Viewer(merchant=m, store=st)))
    assert kicks == [1]
    bus.subs.clear()  # el generador nunca corrió; quitamos la suscripción
    assert resp.media_type == "text/event-stream"


def test_loop_polls_on_kick_only_while_a_screen_is_connected(client, fake_pey, monkeypatch):
    add_charge("QRFIJO", kind="fixed")
    monkeypatch.setattr(config, "RECOVERY_POLL_SECONDS", 3600)  # solo despierta con kick

    async def scenario():
        rec = Recovery()
        polls = []
        real_poll = rec.poll_once

        async def counted(merchant_ids=None):
            polls.append(merchant_ids)
            return await real_poll(merchant_ids)
        rec.poll_once = counted
        task = asyncio.create_task(rec.run())
        try:
            rec.kick()
            await asyncio.sleep(0.05)
            assert polls == []  # nadie conectado: no se gasta una consulta a pey

            q = bus.subscribe(demo_ids()[0])
            rec.kick()
            await asyncio.sleep(0.05)
            assert polls == [{demo_ids()[0]}]
            bus.unsubscribe(q)
        finally:
            task.cancel()

    run(scenario())


def test_recovery_is_off_without_api_key(client, fake_pey, monkeypatch):
    add_charge("QRFIJO", kind="fixed")
    monkeypatch.setattr(config, "PEY_API_KEY", "")
    assert run(recovery.poll_once()) == 0
    assert fake_pey["calls"] == []


def test_merchant_with_own_clabe_is_recovered_from_its_bank_account(client, fake_pey, monkeypatch):
    """Un negocio con CLABE propia se revisa con una sola consulta: GET /transaction/bank-account/{id}."""
    mid, sid = add_merchant(phone="5511112222", bank_account_id="BA_LUPITA")
    add_charge("QRLUPITA", kind="fixed", merchant=(mid, sid))
    calls = []

    async def list_account(client, bank_account_id, token=None):
        calls.append(bank_account_id)
        return {"items": [
            {**pey_item("TXQ", 30, NOW - 10), "payableType": "API_CODI_QR", "payableId": "QRLUPITA"},
            {**pey_item("TXP", 45, NOW - 20), "payableType": "API_CODI_PN", "payableId": "PN1"},
        ], "nextToken": None}

    monkeypatch.setattr(pey, "list_bank_account_transactions", list_account)
    assert run(recovery.poll_once({mid})) == 2
    assert calls == ["BA_LUPITA"]
    assert payment("TXQ")["merchant_id"] == mid and payment("TXQ")["kind"] == "fixed"
    assert payment("TXP")["merchant_id"] == mid
    assert fake_pey["calls"] == []  # la demo no se consultó: no estaba en la lista


def test_only_merchants_with_open_screens_are_polled(client, fake_pey, monkeypatch):
    add_charge("QRFIJO", kind="fixed")
    mid, _ = add_merchant(phone="5511112222")
    seen = []

    async def list_account(client, bank_account_id, token=None):
        seen.append(bank_account_id)
        return {"items": [], "nextToken": None}

    monkeypatch.setattr(pey, "list_bank_account_transactions", list_account)
    run(recovery.poll_once({mid}))
    assert seen == ["BA_LUPITA"] and fake_pey["calls"] == []
