"""Administración: ver negocios y ligar una CLABE que ya se registró en pey (sin registrarla otra vez)."""

import httpx
import pytest

from app import config, pey

TOKEN = "admin-token-de-prueba-largo-123456"
H = {"Authorization": f"Bearer {TOKEN}"}
LINK = {"bankAccountId": "BA_VICTOR", "phone": "5544445555", "pin": "730146", "firstName": "Víctor",
        "lastName": "Hinojosa", "businessName": "Mi negocio"}


@pytest.fixture
def admin(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", TOKEN)
    calls = {"register": 0, "status": "PENDING"}

    async def get_account(bank_account_id):
        if bank_account_id != "BA_VICTOR":
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "http://x"), response=httpx.Response(404))
        return {"id": bank_account_id, "codiStatus": calls["status"], "clabe": "012180001234567899", "name": "VICTOR HINOJOSA"}

    async def register(*a, **kw):
        calls["register"] += 1
        raise AssertionError("no debe registrar otra vez")

    async def create_qr(amount, concept, expiration, bank_account_id=None):
        return "QRV", "QRSTRING", "1"

    monkeypatch.setattr(pey, "get_bank_account", get_account)
    monkeypatch.setattr(pey, "register_bank_account", register)
    monkeypatch.setattr(pey, "create_qr", create_qr)
    return calls


def test_admin_is_off_without_token(anon):
    assert anon.get("/api/admin/merchants", headers=H).status_code == 404


def test_admin_needs_the_token(anon, admin):
    assert anon.get("/api/admin/merchants").status_code == 401
    assert anon.get("/api/admin/merchants", headers={"Authorization": "Bearer otro"}).status_code == 401


def test_admin_locks_after_ten_wrong_tokens(anon, admin):
    for _ in range(10):
        anon.get("/api/admin/merchants", headers={"Authorization": "Bearer otro"})
    assert anon.get("/api/admin/merchants", headers=H).status_code == 429


def test_link_existing_pending_account_and_log_in(anon, admin):
    r = anon.post("/api/admin/merchants/link", json=LINK, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["codiStatus"] == "PENDING" and r.json()["clabe4"] == "7899" and admin["register"] == 0

    anon.post("/api/auth/login", json={"phone": "5544445555", "pin": "730146"})
    m = anon.get("/api/me").json()["merchant"]
    assert m["codiStatus"] == "PENDING" and m["bank"] == "BBVA" and m["businessName"] == "Mi negocio"

    listed = anon.get("/api/admin/merchants", headers=H).json()["merchants"]
    assert ("Mi negocio", "PENDING", "5544445555") in [(x["businessName"], x["codiStatus"], x["phone"]) for x in listed]


def test_link_active_account_creates_its_fixed_qr(anon, admin):
    admin["status"] = "ACTIVE"
    anon.post("/api/admin/merchants/link", json=LINK, headers=H)
    anon.post("/api/auth/login", json={"phone": "5544445555", "pin": "730146"})
    assert anon.get("/api/fixed-qr").json()["fixed"]["id"] == "QRV"


def test_link_rejects_unknown_or_already_linked(anon, admin):
    r = anon.post("/api/admin/merchants/link", json={**LINK, "bankAccountId": "BA_OTRA"}, headers=H)
    assert r.status_code == 404
    anon.post("/api/admin/merchants/link", json=LINK, headers=H)
    again = anon.post("/api/admin/merchants/link", json={**LINK, "phone": "5566667777"}, headers=H)
    assert again.status_code == 409
