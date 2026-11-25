"""Webhook de pey: firma, duplicados, montos, ventas pagadas dos veces y el registro de webhook-id."""

import base64

from conftest import NOW, add_charge, count, payment, qr_payment, sign_and_post

from app import payments


def test_invalid_signature_is_rejected_and_nothing_is_saved(client, events):
    add_charge("QRFIJO", kind="fixed")
    other_secret = "whsec_" + base64.b64encode(b"a-different-secret-of-32-bytes!!").decode()

    r = sign_and_post(client, qr_payment("TX1", 50), secret=other_secret)

    assert r.status_code == 401
    assert count("payments") == 0
    assert count("webhook_events") == 0
    assert events() == []


def test_tampered_body_is_rejected(client):
    add_charge("QRFIJO", kind="fixed")
    r = sign_and_post(client, qr_payment("TX1", 50))
    assert r.status_code == 200
    # mismo encabezado de firma, otro cuerpo
    req = r.request
    r2 = client.post("/webhooks/pey", content=req.content.replace(b"50", b"5000"), headers=dict(req.headers))
    assert r2.status_code == 401


def test_missing_secret_returns_503(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "PEY_WEBHOOK_SECRET", "")
    r = sign_and_post(client, qr_payment("TX1", 50))
    assert r.status_code == 503


def test_valid_webhook_is_saved_with_its_three_timestamps(client, events, clock):
    add_charge("QRFIJO", kind="fixed")
    clock.now = NOW + 5  # el aviso llega 5 s después del pago

    r = sign_and_post(client, qr_payment("TX1", 85.5, paid_at=NOW))

    assert r.json() == {"ok": True}
    p = payment("TX1")
    assert (p["paid_at"], p["received_at"], p["created_at"]) == (NOW, NOW + 5, NOW + 5)
    assert p["source"] == "webhook" and p["kind"] == "fixed" and p["amount"] == 85.5
    assert p["payer_bank"] == "Santander" and p["payer_clabe4"] == "6460"
    [e] = events()
    assert e["type"] == "payment" and e["announced"] and e["speech"] == "Recibiste 85 pesos con 50 centavos"


def test_duplicate_webhook_same_id_is_ignored(client, events):
    add_charge("QRFIJO", kind="fixed")

    first = sign_and_post(client, qr_payment("TX1", 50), webhook_id="msg_1")
    again = sign_and_post(client, qr_payment("TX1", 50), webhook_id="msg_1")

    assert first.json() == {"ok": True}
    assert again.json() == {"ok": True, "duplicate": True}
    assert count("payments") == 1
    assert len(events()) == 1  # se anunció una sola vez


def test_same_transaction_with_new_webhook_id_is_not_announced_twice(client, events):
    add_charge("QRFIJO", kind="fixed")

    sign_and_post(client, qr_payment("TX1", 50), webhook_id="msg_1")
    sign_and_post(client, qr_payment("TX1", 50), webhook_id="msg_2")

    assert count("payments") == 1
    assert len(events()) == 1


def test_failed_processing_is_not_marked_as_seen_so_the_retry_works(client, events, monkeypatch):
    """Antes el webhook-id se guardaba ANTES de procesar: si algo fallaba, el reintento de pey se tiraba como duplicado."""
    add_charge("QRFIJO", kind="fixed")
    real = payments.record_payment

    async def boom(*a, **kw):
        raise RuntimeError("disco lleno")

    monkeypatch.setattr("app.routes.webhooks.record_payment", boom)
    r = sign_and_post(client, qr_payment("TX1", 50), webhook_id="msg_1")
    assert r.status_code == 500
    assert count("webhook_events") == 0 and count("payments") == 0

    monkeypatch.setattr("app.routes.webhooks.record_payment", real)
    retry = sign_and_post(client, qr_payment("TX1", 50), webhook_id="msg_1")
    assert retry.json() == {"ok": True}
    assert count("payments") == 1 and count("webhook_events") == 1
    assert len(events()) == 1


def test_incorrect_amount_is_saved_as_paid_and_flagged(client, events):
    add_charge("QR90", kind="amount", amount=90)

    sign_and_post(client, qr_payment("TX1", 50, qr_id="QR90"))

    p = payment("TX1")
    assert p["amount"] == 50 and p["expected_amount"] == 90
    [e] = events()
    assert e["amountMismatch"] and e["expectedAmount"] == 90 and e["speech"] == "Recibiste 50 pesos"
    # el historial también lo marca (antes solo se veía en el aviso en vivo)
    [h] = client.get("/api/payments").json()["payments"]
    assert h["amountMismatch"] and h["expectedAmount"] == 90


def test_exact_amount_is_not_flagged(client, events):
    add_charge("QR90", kind="amount", amount=90)
    sign_and_post(client, qr_payment("TX1", 90, qr_id="QR90"))
    assert not events()[0]["amountMismatch"]


def test_two_payments_for_the_same_sale_flags_the_second(client, events):
    """El cliente pagó la solicitud al celular y también el QR de respaldo de la misma venta."""
    add_charge("PUSH1", kind="push", amount=120, sale_id="SALE1", phone="5512345678")
    add_charge("QRBACKUP", kind="amount", amount=120, sale_id="SALE1")

    sign_and_post(client, {"type": "codi.pn.payment_received", "transactionId": "PUSH1", "amount": 120,
                           "datePaid": NOW, "metadata": {}}, webhook_id="msg_1")
    sign_and_post(client, qr_payment("TX2", 120, qr_id="QRBACKUP"), webhook_id="msg_2")

    assert payment("PUSH1")["duplicate_sale"] == 0
    assert payment("TX2")["duplicate_sale"] == 1
    first, second = events()
    assert first["kind"] == "push" and first["phone4"] == "5678" and not first["duplicateSale"]
    assert second["duplicateSale"]


def test_same_amount_qr_paid_twice_keeps_the_first_payment_on_the_charge(client):
    add_charge("QR90", kind="amount", amount=90)
    sign_and_post(client, qr_payment("TX1", 90, qr_id="QR90"), webhook_id="msg_1")
    sign_and_post(client, qr_payment("TX2", 90, qr_id="QR90"), webhook_id="msg_2")

    assert payment("TX2")["duplicate_sale"] == 1
    from app.db import connect
    with connect() as conn:
        assert conn.execute("SELECT transaction_id FROM charges WHERE id='QR90'").fetchone()[0] == "TX1"


def test_late_webhook_is_saved_quietly(client, events, clock):
    """pey reintentó 10 minutos después: va al historial pero la bocina no lo grita."""
    add_charge("QRFIJO", kind="fixed")
    clock.now = NOW + 600

    sign_and_post(client, qr_payment("TX1", 50, paid_at=NOW))

    assert payment("TX1") is not None
    [e] = events()
    assert e["type"] == "history" and not e["announced"]


def test_unknown_qr_is_saved_as_external(client):
    sign_and_post(client, qr_payment("TX1", 30, qr_id="OTRO"))
    assert payment("TX1")["kind"] == "external"
