import re

from conftest import FakeCommands, make_client


def _code_from_outbox(client) -> str:
    body = client.app.state._test_sms.outbox[-1].body
    return re.search(r"\b(\d{6})\b", body).group(1)


def test_send_then_verify_with_code_from_sms():
    c = make_client(FakeCommands())
    sent = c.post("/otp/send", json={"run_id": "r1", "mc": "133655"}).json()
    assert sent["status"] == "sent"
    assert "*" in sent["to_masked"] and "code" not in sent       # code never in the response
    assert len(c.app.state._test_sms.outbox) == 1                # ...only in the (stub) SMS
    v = c.post("/otp/verify", json={"run_id": "r1", "mc": "133655", "code": _code_from_outbox(c)})
    assert v.json()["status"] == "verified"


def test_wrong_code_three_times_locks_out():
    c = make_client(FakeCommands())
    c.post("/otp/send", json={"run_id": "r1", "mc": "133655"})
    wrong = "000001" if _code_from_outbox(c) != "000001" else "000002"
    last = None
    for _ in range(3):
        last = c.post("/otp/verify", json={"run_id": "r1", "mc": "133655", "code": wrong}).json()
    assert last["status"] == "locked_out"


def test_verify_before_send_is_locked_out():
    c = make_client(FakeCommands())
    v = c.post("/otp/verify", json={"run_id": "r1", "mc": "133655", "code": "123456"})
    assert v.json()["status"] == "locked_out"


def test_send_to_unknown_carrier_is_not_found():
    c = make_client(FakeCommands())
    r = c.post("/otp/send", json={"run_id": "r1", "mc": "000000"})  # stub not-found sentinel
    assert r.json()["status"] == "not_found"


def test_code_is_never_in_the_send_response_body():
    c = make_client(FakeCommands())
    raw = c.post("/otp/send", json={"run_id": "r1", "mc": "133655"}).text
    assert _code_from_outbox(c) not in raw  # the real code does not appear anywhere in the body
