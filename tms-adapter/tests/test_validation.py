"""Malformed input must never fail a HappyRobot run.

Every tool endpoint must answer HTTP 200 + {"status": "invalid_request"} for a missing,
empty, blank, or wrong-type required field — NOT FastAPI's default 422 (a 4xx the
workflow's "Ignore 5XX" net does not catch) nor a 500. This extends the adapter's
200 + status invariant to request-validation errors.
"""
from conftest import FakeCommands, make_client


def _client():
    return make_client(FakeCommands())


def test_offers_evaluate_missing_field_is_200_invalid_request():
    r = _client().post("/offers/evaluate", json={"run_id": "r1", "load_id": "LD1"})  # no carrier_offer
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_offers_evaluate_wrong_type_is_200_invalid_request():
    r = _client().post("/offers/evaluate", json={"run_id": "r1", "load_id": "LD1", "carrier_offer": "lots"})
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_offers_log_missing_field_is_200_invalid_request():
    r = _client().post("/offers/log", json={"run_id": "r1", "load_id": "LD1"})  # no carrier_offer
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_bookings_missing_field_is_200_invalid_request():
    r = _client().post("/bookings", json={"run_id": "r1", "load_id": "LD1", "mc_number": "133655"})  # no agreed_rate
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_loads_get_empty_load_id_is_200_invalid_request():
    r = _client().post("/loads/get", json={"load_id": ""})
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_otp_send_empty_mc_is_200_invalid_request():
    # The historical 500: an empty `mc` passed Pydantic, then fmcsa.lookup raised ValueError.
    r = _client().post("/otp/send", json={"run_id": "r1", "mc": ""})
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_otp_send_blank_mc_is_200_invalid_request():
    # Whitespace-only is also blank once stripped, so it routes the same way (no 500).
    r = _client().post("/otp/send", json={"run_id": "r1", "mc": "   "})
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_otp_verify_empty_code_is_200_invalid_request():
    r = _client().post("/otp/verify", json={"run_id": "r1", "mc": "133655", "code": ""})
    assert r.status_code == 200 and r.json()["status"] == "invalid_request"


def test_validation_error_body_is_generic_not_leaky():
    # The error payload must not echo the offending value — it could carry a secret like an
    # OTP code. Send a 6-digit "code" alongside a field that fails validation and assert the
    # code never appears in the response (FastAPI's default 422 would have echoed the input).
    raw = _client().post("/otp/verify", json={"run_id": "r1", "mc": "", "code": "424242"}).text
    assert "424242" not in raw
