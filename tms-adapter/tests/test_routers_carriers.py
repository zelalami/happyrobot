from conftest import FakeCommands, make_client


def test_find_carrier_active(client):
    r = client.post("/carriers/find", json={"mc": "133655"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "found"
    carrier = body["carrier"]
    assert carrier["authority"]["allowed_to_operate"] is True
    assert carrier["mc_number"] == "133655"


def test_find_carrier_not_found_is_200_status(client):
    r = client.post("/carriers/find", json={"mc": "000000"})  # stub sentinel
    assert r.status_code == 200 and r.json() == {"status": "not_found"}


def test_find_carrier_not_authorized(client):
    r = client.post("/carriers/find", json={"mc": "999999"})  # stub sentinel
    assert r.status_code == 200
    assert r.json()["carrier"]["authority"]["allowed_to_operate"] is False


def test_find_carrier_requires_identifier(client):
    r = client.post("/carriers/find", json={})
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_find_carrier_never_leaks_raw_phone(client):
    body = client.post("/carriers/find", json={"mc": "133655"}).json()
    carrier = body["carrier"]
    assert "registered_phone" not in carrier            # raw never exposed
    assert carrier["registered_phone_masked"].startswith("+1") and "*" in carrier["registered_phone_masked"]


# ------------------------------- bearer auth ------------------------------- #
def test_auth_rejected_without_bearer_when_key_set():
    c = make_client(FakeCommands(), adapter_api_key="secret")
    assert c.post("/carriers/find", json={"mc": "133655"}).status_code == 401


def test_auth_accepted_with_correct_bearer():
    c = make_client(FakeCommands(), adapter_api_key="secret")
    r = c.post("/carriers/find", json={"mc": "133655"}, headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200 and r.json()["status"] == "found"
