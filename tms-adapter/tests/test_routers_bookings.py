from conftest import FakeCommands, make_client
from app.tms.commands import BookingResult

ECON = {"max_buy": 1999, "posted_rate": 1704}


def _accept(client, run, load, rate):
    """Drive an evaluate that accepts `rate`, recording the acceptance token server-side."""
    client.app.state.load_economics[load] = dict(ECON)
    b = client.post("/offers/evaluate", json={"run_id": run, "load_id": load, "carrier_offer": rate}).json()
    assert b["decision"] == "accept"


def test_booking_succeeds_after_a_matching_accept():
    c = make_client(FakeCommands(book=BookingResult("booked", booking_ref="BR1", confirmed=True)))
    _accept(c, "r1", "LD00271", 1950)
    r = c.post("/bookings", json={"run_id": "r1", "load_id": "LD00271", "mc_number": "872144", "agreed_rate": 1950})
    b = r.json()
    assert b["status"] == "booked" and b["booking_ref"] == "BR1" and b["agreed_rate"] == 1950


def test_booking_without_a_recorded_accept_is_refused_and_never_calls_book():
    fake = FakeCommands(book=BookingResult("booked", booking_ref="BR1", confirmed=True))
    c = make_client(fake)
    c.app.state.load_economics["LD00271"] = dict(ECON)  # ceiling known, but NO accept recorded
    r = c.post("/bookings", json={"run_id": "r1", "load_id": "LD00271", "mc_number": "872144", "agreed_rate": 1950})
    assert r.json()["status"] == "rate_not_accepted"
    assert fake.book_calls == 0  # never send LOAD_BOOK for a non-accepted rate


def test_booking_a_different_rate_than_accepted_is_refused():
    fake = FakeCommands(book=BookingResult("booked", booking_ref="BR1", confirmed=True))
    c = make_client(fake)
    _accept(c, "r1", "LD00271", 1950)
    r = c.post("/bookings", json={"run_id": "r1", "load_id": "LD00271", "mc_number": "872144", "agreed_rate": 1975})
    assert r.json()["status"] == "rate_not_accepted" and fake.book_calls == 0


def test_booking_fails_closed_without_ceiling():
    c = make_client(FakeCommands(book=BookingResult("booked", booking_ref="BR1")))
    c.app.state.load_economics["LDX"] = {"max_buy": None, "posted_rate": 1704}
    r = c.post("/bookings", json={"run_id": "r1", "load_id": "LDX", "mc_number": "m", "agreed_rate": 1000})
    assert r.json()["status"] == "ceiling_unavailable"


def test_booking_ambiguous_escalates():
    c = make_client(FakeCommands(book=BookingResult("ambiguous", note="verify failed")))
    _accept(c, "r1", "LD00271", 1950)
    r = c.post("/bookings", json={"run_id": "r1", "load_id": "LD00271", "mc_number": "872144", "agreed_rate": 1950})
    b = r.json()
    assert b["status"] == "booking_ambiguous" and b["action"] == "escalate_to_human"


def test_booking_already_booked():
    c = make_client(FakeCommands(book=BookingResult("already_booked")))
    _accept(c, "r1", "LD00271", 1950)
    r = c.post("/bookings", json={"run_id": "r1", "load_id": "LD00271", "mc_number": "872144", "agreed_rate": 1950})
    assert r.json()["status"] == "already_booked"
