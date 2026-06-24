from conftest import LD271, FakeCommands, make_client

ECON = {"max_buy": 1999, "posted_rate": 1704}


def test_evaluate_counter_then_accept_across_rounds():
    c = make_client(FakeCommands())
    c.app.state.load_economics["LD00271"] = dict(ECON)
    r1 = c.post("/offers/evaluate", json={"run_id": "r1", "load_id": "LD00271", "carrier_offer": 2100}).json()
    assert r1["decision"] == "counter" and r1["suggested_counter"] == 1750 and r1["rounds_remaining"] == 2
    r2 = c.post("/offers/evaluate", json={"run_id": "r1", "load_id": "LD00271", "carrier_offer": 1990}).json()
    assert r2["decision"] == "accept" and r2["agreed_rate"] == 1990


def test_evaluate_never_returns_ceiling():
    c = make_client(FakeCommands())
    c.app.state.load_economics["LD00271"] = dict(ECON)
    raw = c.post("/offers/evaluate", json={"run_id": "r1", "load_id": "LD00271", "carrier_offer": 2100}).text
    assert "1999" not in raw and "max_buy" not in raw.lower()


def test_evaluate_fetches_economics_when_not_cached():
    c = make_client(FakeCommands(get=LD271))  # not pre-seeded -> endpoint fetches LOAD_GET
    b = c.post("/offers/evaluate", json={"run_id": "r1", "load_id": "LD00271", "carrier_offer": 1990}).json()
    assert b["decision"] == "accept"
    assert c.app.state.load_economics["LD00271"]["max_buy"] == 1999  # seeded server-side


def test_evaluate_round_cap_after_three():
    c = make_client(FakeCommands())
    c.app.state.load_economics["LD00271"] = dict(ECON)
    last = None
    for _ in range(4):
        last = c.post("/offers/evaluate", json={"run_id": "r1", "load_id": "LD00271", "carrier_offer": 5000}).json()
    assert last["decision"] == "reject" and last["reason"] == "max_rounds_exhausted"


def test_evaluate_fails_closed_without_ceiling():
    c = make_client(FakeCommands())
    c.app.state.load_economics["LDX"] = {"max_buy": None, "posted_rate": 1704}
    b = c.post("/offers/evaluate", json={"run_id": "r1", "load_id": "LDX", "carrier_offer": 1500}).json()
    assert b["decision"] == "reject" and b["reason"] == "ceiling_unavailable" and b["ceiling_available"] is False


def test_log_offer_appends_audit():
    c = make_client(FakeCommands())
    r = c.post("/offers/log", json={"run_id": "r1", "load_id": "LD00271", "carrier_offer": 2000, "notes": "held"})
    assert r.json() == {"status": "logged"}
    assert c.app.state.audit[-1]["carrier_offer"] == 2000
