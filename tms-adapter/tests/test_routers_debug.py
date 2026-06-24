"""The /debug/outbox route: reads the stub SMS outbox to surface the OTP code.

It exists so a full happy-path (incl. a successful OTP verify) is drivable over
HTTP — the OTP code is never returned by /otp/send. SMS is stub-only (no real
provider wired), so the route is mounted unconditionally and bearer-protected; a
deployment with a real SMS provider would drop it.
"""
import re

from conftest import make_client

from app.config import Settings


def test_outbox_mounted_even_when_stubs_disabled():
    # SMS is stub-only, so the outbox is the only way to read the OTP code; the
    # route is mounted regardless of use_stubs (and is bearer-protected).
    prod = Settings(_env_file=None, tms_host="h", tms_port=1, tms_token="t", use_stubs=False)
    c = make_client(settings=prod)
    r = c.get("/debug/outbox")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_outbox_exposes_sent_otp_code_under_stubs():
    c = make_client()  # use_stubs=True

    empty = c.get("/debug/outbox")
    assert empty.status_code == 200 and empty.json() == {"status": "ok", "messages": []}

    sent = c.post("/otp/send", json={"run_id": "r1", "mc": "123456"})
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    assert "code" not in sent.json()  # the code never rides the response

    msgs = c.get("/debug/outbox").json()["messages"]
    assert len(msgs) == 1
    code = re.search(r"\d{6}", msgs[0]["body"]).group()  # but it IS readable from the stub outbox

    verified = c.post("/otp/verify", json={"run_id": "r1", "mc": "123456", "code": code})
    assert verified.json()["status"] == "verified"
