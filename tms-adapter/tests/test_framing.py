from pathlib import Path

import pytest

from app.tms.errors import TMSError
from app.tms.faults import TMSFault, TMSFaultError
from app.tms.framing import decode_response, encode_request

TRANSCRIPTS = Path(__file__).resolve().parent / "fixtures" / "transcripts"
ALL_FIXTURES = sorted(TRANSCRIPTS.glob("*.txt"))
# query_orig_CO.txt is a LIVE capture of the TMS "malformed" fault injection: a
# stray `|XX        |` token spliced into an otherwise-valid record, before a
# valid END. We reject (and retry) rather than salvage it — so it is the
# one capture that must NOT decode cleanly.
MALFORMED_CAPTURES = {"query_orig_CO.txt"}
CLEAN_FIXTURES = [p for p in ALL_FIXTURES if p.name not in MALFORMED_CAPTURES]


# --------------------------------------------------------------------------- #
# Encoder
# --------------------------------------------------------------------------- #
def test_encode_orders_cmd_then_auth():
    assert (
        encode_request("DEBUG_ECHO", "TKN", {"MSG": "HELLO"})
        == b"CMD:DEBUG_ECHO|AUTH:TKN|MSG:HELLO\r\n"
    )


def test_encode_uppercases_field_names():
    assert encode_request("LOAD_GET", "T", {"load_id": "LD1"}) == b"CMD:LOAD_GET|AUTH:T|LOAD_ID:LD1\r\n"


def test_encode_no_fields():
    assert encode_request("DEBUG_ECHO", "T") == b"CMD:DEBUG_ECHO|AUTH:T\r\n"


def test_encode_rejects_pipe_in_value():
    with pytest.raises(ValueError):
        encode_request("X", "T", {"A": "b|c"})


def test_encode_rejects_crlf_in_value():
    with pytest.raises(ValueError):
        encode_request("X", "T", {"A": "b\r\nc"})


def test_encode_rejects_non_ascii():
    with pytest.raises(ValueError):
        encode_request("X", "T", {"A": "café"})


def test_encode_rejects_oversize_frame():
    with pytest.raises(ValueError):
        encode_request("X", "T", {"A": "z" * 5000})


def test_encode_rejects_illegal_command():
    with pytest.raises(ValueError):
        encode_request("BAD|CMD", "T")


# --------------------------------------------------------------------------- #
# Decoder — against the real TMS captures
# --------------------------------------------------------------------------- #
def test_decode_loadget_ld00271():
    out = decode_response((TRANSCRIPTS / "loadget_LD00271.txt").read_bytes())
    assert out.error is None and out.seen_end
    assert len(out.records) == 1
    r = out.records[0]
    assert r["LOAD_ID"] == "LD00271"
    assert r["ORIG_CITY"] == "Huntsville" and r["ORIG_STATE"] == "AL"
    assert r["DEST_CITY"] == "Austin" and r["DEST_STATE"] == "TX"
    assert r["EQTYPE"] == "DRY_VAN" and r["STATUS"] == "OPEN"
    assert r["RATE"] == 1704 and r["MAX_BUY"] == 1999 and r["MILES"] == 719
    assert r["WEIGHT"] == 24138 and r["PIECES"] == 3
    assert r["PICKUP_DT"] == "2026-06-25T17:20:00"
    assert r["DELIVERY_DT"] == "2026-06-26T14:20:00"
    assert isinstance(r["NOTES"], str) and r["NOTES"].startswith("Live unload")
    # MAX_BUY sits ABOVE the posted rate (the rate inversion).
    assert r["MAX_BUY"] > r["RATE"]


def test_decode_query_subset_omits_get_only_fields():
    out = decode_response((TRANSCRIPTS / "query_orig_AL.txt").read_bytes())
    assert out.error is None and out.seen_end and len(out.records) == 2
    for r in out.records:
        for absent in ("MAX_BUY", "WEIGHT", "COMMODITY", "PIECES", "DIMS", "NOTES"):
            assert absent not in r


@pytest.mark.parametrize("path", CLEAN_FIXTURES, ids=lambda p: p.name)
def test_clean_captures_decode_cleanly(path):
    """Every clean real capture parses with a terminal, no error, and >=1 record."""
    out = decode_response(path.read_bytes())
    assert out.seen_end and out.error is None and out.records


def test_live_malformed_fault_capture_is_detected():
    """The one live capture carrying the TMS malformed-fault injection is rejected."""
    raw = (TRANSCRIPTS / "query_orig_CO.txt").read_bytes()
    with pytest.raises(TMSFaultError) as e:
        decode_response(raw)
    assert e.value.fault is TMSFault.MALFORMED
    assert "XX" in e.value.detail  # the stray, KEY:VALUE-less token


def test_decode_empty_board():
    out = decode_response(b"END\r\n")
    assert out.seen_end and out.records == [] and out.error is None


def test_decode_err_line_maps_not_found_to_404():
    out = decode_response(b"ERR|CODE:NOT_FOUND|MSG:no such load\r\n")
    assert isinstance(out.error, TMSError)
    assert out.error.code == "NOT_FOUND" and out.error.http_status == 404
    assert out.records == []


def test_decode_bare_token_is_malformed():
    with pytest.raises(TMSFaultError) as e:
        decode_response(b"LOAD_ID:LD1   |GARBAGE\r\nEND\r\n")
    assert e.value.fault is TMSFault.MALFORMED


def test_decode_content_after_end_is_malformed():
    with pytest.raises(TMSFaultError) as e:
        decode_response(b"END\r\nLOAD_ID:LD1   \r\n")
    assert e.value.fault is TMSFault.MALFORMED


def test_decode_truncated_is_partial():
    with pytest.raises(TMSFaultError) as e:
        decode_response(b"LOAD_ID:LD00271     |RATE:1704    \r\n")
    assert e.value.fault is TMSFault.PARTIAL


def test_decode_overwidth_value_is_malformed():
    with pytest.raises(TMSFaultError) as e:
        decode_response(b"LOAD_ID:LD1   |RATE:123456789\r\nEND\r\n")
    assert e.value.fault is TMSFault.MALFORMED


def test_decode_non_ascii_is_malformed():
    with pytest.raises(TMSFaultError) as e:
        decode_response(b"LOAD_ID:LD1   |COMMODITY:caf\xe9\r\nEND\r\n")
    assert e.value.fault is TMSFault.MALFORMED
