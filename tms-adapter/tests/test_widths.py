import pytest

from app.tms.faults import TMSFault, TMSFaultError
from app.tms.widths import normalize_field, normalize_record


def test_numeric_space_padded():
    assert normalize_field("RATE", "1704    ") == 1704
    assert normalize_field("MAX_BUY", "1999    ") == 1999


def test_numeric_zero_padded_does_not_lstrip():
    # int() handles leading zeros; lstrip('0') would corrupt "0000000" -> "".
    assert normalize_field("RATE", "0001950") == 1950
    assert normalize_field("WEIGHT", "0000000") == 0


def test_numeric_blank_is_none():
    assert normalize_field("RATE", "        ") is None


def test_numeric_nonnumeric_is_malformed():
    with pytest.raises(TMSFaultError) as e:
        normalize_field("RATE", "12A4    ")
    assert e.value.fault is TMSFault.MALFORMED


def test_text_rstrip_only():
    assert normalize_field("ORIG_CITY", "Huntsville" + " " * 20) == "Huntsville"


def test_notes_blank_is_none():
    assert normalize_field("NOTES", " " * 120) is None


def test_date_to_iso():
    assert normalize_field("PICKUP_DT", "20260625172000") == "2026-06-25T17:20:00"


def test_date_blank_is_none():
    assert normalize_field("DELIVERY_DT", " " * 14) is None


def test_date_invalid_is_malformed():
    with pytest.raises(TMSFaultError) as e:
        normalize_field("PICKUP_DT", "2026XX25172000")
    assert e.value.fault is TMSFault.MALFORMED


def test_token_state_and_id_kept():
    assert normalize_field("ORIG_STATE", "AL") == "AL"
    assert normalize_field("LOAD_ID", "LD00271     ") == "LD00271"


def test_overwidth_is_malformed():
    with pytest.raises(TMSFaultError) as e:
        normalize_field("RATE", "123456789")  # 9 chars > width 8
    assert e.value.fault is TMSFault.MALFORMED


def test_unknown_field_kept_and_trimmed():
    # A new TMS column we have never seen must not crash or width-fail.
    assert normalize_field("FUTURE_COL", "hello   ") == "hello"


def test_normalize_record_mixed():
    rec = normalize_record({
        "LOAD_ID": "LD00271     ",
        "RATE": "1704    ",
        "ORIG_STATE": "AL",
        "NOTES": " " * 120,
    })
    assert rec == {"LOAD_ID": "LD00271", "RATE": 1704, "ORIG_STATE": "AL", "NOTES": None}
