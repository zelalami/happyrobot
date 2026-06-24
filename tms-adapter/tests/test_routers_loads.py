import json

from conftest import LD271, QUERY_AL, FakeCommands, make_client
from app.tms.errors import TMSError
from app.tms.faults import TMSFault, TMSFaultError


# ------------------------------- search ------------------------------------ #
def test_search_returns_mapped_loads():
    c = make_client(FakeCommands(query=QUERY_AL))
    r = c.post("/loads/search", json={"origin_state": "AL", "equipment_type": "Dry Van"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and len(body["loads"]) == 2
    first = body["loads"][0]
    assert first["reference_number"] == "LD00269"
    assert first["equipment_type"] == "Reefer"        # TMS REEFER -> bridge label
    assert first["status"] == "available"             # OPEN -> available


def test_search_filters_out_booked_loads():
    # A covered load can't be booked, so it must never be pitched. Mark one of the two OPEN
    # records as booked (non-OPEN status) and assert only the still-available one comes back.
    booked = {**QUERY_AL[0], "STATUS": "PENDING"}      # LD00269 now covered
    c = make_client(FakeCommands(query=[booked, QUERY_AL[1]]))
    loads = c.post("/loads/search", json={"origin_state": "AL"}).json()["loads"]
    refs = [l["reference_number"] for l in loads]
    assert "LD00269" not in refs                       # covered -> not pitched
    assert "LD00271" in refs and all(l["status"] == "available" for l in loads)


def test_search_booked_loads_do_not_consume_pitch_slots():
    # Filtering happens BEFORE the top-N cut: an available load still surfaces even when
    # covered loads precede it in the TMS result order.
    booked = {**QUERY_AL[0], "STATUS": "PENDING"}
    c = make_client(FakeCommands(query=[booked, booked, booked, QUERY_AL[1]]))
    loads = c.post("/loads/search", json={"origin_state": "AL"}).json()["loads"]
    assert [l["reference_number"] for l in loads] == ["LD00271"]


def test_search_all_booked_is_ok_with_empty_loads():
    # A lane with nothing bookable is a normal outcome (status ok, empty list) — not an error.
    booked = {**QUERY_AL[0], "STATUS": "COVERED"}
    r = make_client(FakeCommands(query=[booked])).post("/loads/search", json={"origin_state": "AL"})
    assert r.status_code == 200 and r.json() == {"status": "ok", "loads": []}


def test_search_never_includes_max_buy():
    c = make_client(FakeCommands(query=QUERY_AL))
    raw = c.post("/loads/search", json={"origin_state": "AL"}).text
    assert "max_buy" not in raw.lower() and "MAX_BUY" not in raw


def test_search_requires_a_filter():
    c = make_client(FakeCommands(query=[]))
    r = c.post("/loads/search", json={})
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_search_tms_fault_is_200_unavailable():
    c = make_client(FakeCommands(query_exc=TMSFaultError(TMSFault.TIMEOUT)))
    r = c.post("/loads/search", json={"origin_state": "AL"})
    assert r.status_code == 200 and r.json()["status"] == "tms_unavailable"


# ------------------------------- get --------------------------------------- #
def test_get_load_returns_detail_without_ceiling():
    c = make_client(FakeCommands(get=LD271))
    r = c.post("/loads/get", json={"load_id": "LD00271"})
    assert r.status_code == 200
    load = r.json()["load"]
    assert load["reference_number"] == "LD00271"
    assert load["posted_carrier_rate"] == 1704
    assert load["ceiling_available"] is True          # we HAVE the ceiling...
    assert "max_buy" not in json.dumps(load).lower()  # ...but never serialize it
    assert "1999" not in json.dumps(load)             # the actual ceiling value


def test_get_load_seeds_economics_cache_server_side():
    c = make_client(FakeCommands(get=LD271))
    c.post("/loads/get", json={"load_id": "LD00271"})
    econ = c.app.state.load_economics
    assert econ["LD00271"] == {"max_buy": 1999, "posted_rate": 1704}


def test_get_load_not_found_is_200_status():
    c = make_client(FakeCommands(get_exc=TMSError("NOT_FOUND", "no such load")))
    r = c.post("/loads/get", json={"load_id": "LDZZZ"})
    assert r.status_code == 200 and r.json()["status"] == "not_found"
