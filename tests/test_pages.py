"""Rutas de páginas: la landing vive en /, la bocina en /bocina, y una bocina ya vinculada sigue abriendo en /."""


def test_landing_on_root_and_speaker_on_bocina(anon):
    assert "Escucha cada pago" in anon.get("/").text
    assert "Din · Mostrador" in anon.get("/bocina").text


def test_owner_session_sees_landing_on_root(client):
    assert "Escucha cada pago" in client.get("/").text


def test_paired_speaker_keeps_root(client, anon):
    code = anon.post("/api/devices/pair").json()["code"]
    assert client.post("/api/devices/claim", json={"code": code}).status_code == 200
    anon.get("/api/devices/pair")  # la bocina recoge su cookie de dispositivo
    assert "Din · Mostrador" in anon.get("/").text
