from conftest import FakeCommands, make_client


def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_readyz_ready_when_echo_ok():
    c = make_client(FakeCommands(echo={"auth_ok": True, "fields_parsed": 3}))
    r = c.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "tms": "reachable", "fields_parsed": 3}


def test_readyz_503_when_auth_not_ok():
    c = make_client(FakeCommands(echo={"auth_ok": False, "fields_parsed": None}))
    r = c.get("/readyz")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"
