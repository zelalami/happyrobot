import httpx
import pytest

from app.config import Settings
from app.services.fmcsa import (
    Carrier,
    CarrierNotFound,
    FMCSAUpstreamError,
    LiveFMCSAClient,
    SodaFMCSAClient,
    StubFMCSAClient,
    extract_carrier,
    extract_soda_carrier,
    get_fmcsa_client,
    map_carrier,
    map_soda_carrier,
)

# A representative QCMobile carrier object (documented shape).
ACTIVE_RAW = {
    "allowedToOperate": "Y", "statusCode": "A", "dotNumber": 76830,
    "legalName": "SCHNEIDER NATIONAL CARRIERS INC", "dbaName": "SCHNEIDER",
    "telephone": "(920) 369-5500", "phyState": "WI",
}
INACTIVE_RAW = {"allowedToOperate": "N", "statusCode": "I", "dotNumber": 111, "legalName": "GONE LLC"}


# --------------------------- pure mapping (no network) --------------------- #
def test_map_active_carrier():
    c = map_carrier(ACTIVE_RAW, mc="133655")
    assert c.status == "active" and c.allowed_to_operate is True
    assert c.mc_number == "133655" and c.dot_number == "76830"
    assert c.legal_name == "SCHNEIDER NATIONAL CARRIERS INC"
    assert c.registered_phone == "+19203695500"


def test_map_inactive_carrier_not_authorized():
    c = map_carrier(INACTIVE_RAW, mc="111")
    assert c.status == "not_authorized" and c.allowed_to_operate is False


def test_to_bridge_exposes_masked_phone_only():
    bridge = map_carrier(ACTIVE_RAW, mc="133655").to_bridge()
    assert bridge["registered_phone_masked"] == "+1******5500"
    assert "registered_phone" not in bridge          # raw number never leaves the adapter
    assert bridge["authority"]["allowed_to_operate"] is True


def test_extract_carrier_from_docket_list():
    payload = {"content": [{"carrier": ACTIVE_RAW}], "retrievalDate": "x"}
    assert extract_carrier(payload)["dotNumber"] == 76830


def test_extract_carrier_from_dot_object():
    payload = {"content": {"carrier": ACTIVE_RAW}}
    assert extract_carrier(payload)["legalName"].startswith("SCHNEIDER")


def test_extract_carrier_empty_content_raises_not_found():
    for payload in ({"content": []}, {"content": None}, {}):
        with pytest.raises(CarrierNotFound):
            extract_carrier(payload)


# ------------------------------- stub client ------------------------------- #
async def test_stub_active_carrier():
    c = await StubFMCSAClient().lookup(mc="133655")
    assert c.status == "active" and c.allowed_to_operate is True
    assert c.registered_phone is not None and c.registered_phone.startswith("+1")


async def test_stub_sentinel_not_authorized():
    c = await StubFMCSAClient().lookup(mc="999999")
    assert c.allowed_to_operate is False and c.status == "not_authorized"


async def test_stub_sentinel_not_found():
    with pytest.raises(CarrierNotFound):
        await StubFMCSAClient().lookup(mc="000000")


async def test_stub_is_deterministic():
    a = await StubFMCSAClient().lookup(mc="133655")
    b = await StubFMCSAClient().lookup(mc="133655")
    assert a == b


async def test_stub_requires_an_identifier():
    with pytest.raises(ValueError):
        await StubFMCSAClient().lookup()


# --------------------------- SODA mapping (no network) --------------------- #
# Representative SODA census rows (flat array elements; authority is per-docket).
SODA_ROW_MC = {
    "legal_name": "SCHNEIDER NATIONAL CARRIERS INC", "dba_name": "SCHNEIDER",
    "dot_number": "264184", "phone": "8005586767", "phy_state": "WI",
    "docket1prefix": "MC", "docket1": "133655", "docket1_status_code": "A",
    "status_code": "A",
}
SODA_ROW_MC_SECONDARY = {  # the queried MC sits in docket2; docket1 is an FF (forwarder)
    "legal_name": "MULTI AUTH LLC", "dot_number": "999", "phone": "5125550199",
    "docket1prefix": "FF", "docket1": "555", "docket1_status_code": "A",
    "docket2prefix": "MC", "docket2": "44110", "docket2_status_code": "A",
}
SODA_ROW_INACTIVE = {  # MC authority revoked/inactive
    "legal_name": "REVOKED LLC", "dot_number": "1",
    "docket1prefix": "MC", "docket1": "140", "docket1_status_code": "I", "status_code": "I",
}


def test_map_soda_mc_docket1_active():
    c = map_soda_carrier(SODA_ROW_MC, mc="133655")
    assert c.status == "active" and c.allowed_to_operate is True
    assert c.mc_number == "133655" and c.dot_number == "264184"
    assert c.legal_name.startswith("SCHNEIDER")
    assert c.registered_phone == "+18005586767"


def test_map_soda_mc_in_secondary_docket_matches_on_prefix_and_number():
    c = map_soda_carrier(SODA_ROW_MC_SECONDARY, mc="44110")
    assert c.allowed_to_operate is True and c.mc_number == "44110"


def test_map_soda_inactive_authority_not_authorized():
    c = map_soda_carrier(SODA_ROW_INACTIVE, mc="140")
    assert c.allowed_to_operate is False and c.status == "not_authorized"


def test_map_soda_mc_unmatched_prefix_is_not_authorized():
    # querying MC 555 where 555 exists only as an FF => no MC authority; we must NOT
    # borrow the FF docket's "A" status.
    c = map_soda_carrier(SODA_ROW_MC_SECONDARY, mc="555")
    assert c.allowed_to_operate is False


def test_map_soda_dot_path_uses_primary_docket():
    c = map_soda_carrier(SODA_ROW_MC, dot="264184")
    assert c.allowed_to_operate is True and c.dot_number == "264184"
    assert c.mc_number == "133655"  # surfaced from the primary MC docket


def test_map_soda_dot_path_ff_only_not_authorized():
    # A freight-forwarder-only carrier looked up by DOT must NOT be "active": it
    # holds no MC operating authority, even though its FF docket is active.
    row = {"legal_name": "FORWARDER ONLY LLC", "dot_number": "6682",
           "docket1prefix": "FF", "docket1": "99999", "docket1_status_code": "A", "status_code": "A"}
    c = map_soda_carrier(row, dot="6682")
    assert c.allowed_to_operate is False and c.status == "not_authorized"
    assert c.mc_number is None


def test_map_soda_census_status_alone_not_authorized():
    # A bare census status with no docket data is NOT active MC authority.
    c = map_soda_carrier({"dot_number": "5", "status_code": "A"}, dot="5")
    assert c.allowed_to_operate is False


def test_extract_soda_empty_raises_not_found():
    for payload in ([], None, {}):
        with pytest.raises(CarrierNotFound):
            extract_soda_carrier(payload)


# --------------------------- SODA client (mock transport) ------------------ #
def _soda_transport(rows, *, status=200, capture=None):
    """An httpx MockTransport that records the request and returns canned rows."""
    def handler(request: httpx.Request):
        if capture is not None:
            capture["where"] = request.url.params.get("$where")
            capture["dot"] = request.url.params.get("dot_number")
            capture["app_token"] = request.headers.get("X-App-Token")
        if status != 200:
            return httpx.Response(status, text="upstream error")
        return httpx.Response(200, json=rows)
    return httpx.MockTransport(handler)


async def test_soda_client_active_lookup_builds_mc_where_clause():
    cap = {}
    client = SodaFMCSAClient(transport=_soda_transport([SODA_ROW_MC], capture=cap), app_token="tok-abcdef")
    c = await client.lookup(mc="MC 133655")  # spoken/free-form form
    assert c.allowed_to_operate is True and c.mc_number == "133655"
    assert "docket1prefix='MC' AND docket1='133655'" in cap["where"]
    assert "docket2='133655'" in cap["where"] and "docket3='133655'" in cap["where"]
    assert cap["app_token"] == "tok-abcdef"


async def test_soda_client_sanitizes_soql_injection_to_digits():
    cap = {}
    client = SodaFMCSAClient(transport=_soda_transport([], capture=cap))
    with pytest.raises(CarrierNotFound):
        await client.lookup(mc="133655' OR '1'='1")
    # only digits reached the query — the injected quotes/predicate never appear
    assert "1336551" in cap["where"]            # non-digits stripped: 133655 + 1 + 1
    assert "'1'='1" not in cap["where"]
    assert "OR '1'" not in cap["where"]


async def test_soda_client_not_found_returns_carrier_not_found():
    client = SodaFMCSAClient(transport=_soda_transport([]))
    with pytest.raises(CarrierNotFound):
        await client.lookup(mc="99999999")


async def test_soda_client_unicode_digits_fail_closed():
    # `\d` is Unicode-aware; fullwidth digits must NOT reach the query. With only
    # ASCII digits surviving, a fullwidth-only MC reduces to empty -> fail closed
    # (CarrierNotFound, i.e. 200 not_found), never a 500 or a non-ASCII $where.
    cap = {}
    client = SodaFMCSAClient(transport=_soda_transport([], capture=cap))
    with pytest.raises(CarrierNotFound):
        await client.lookup(mc="４４１１０")  # fullwidth 44110
    assert cap == {}  # request never issued (no usable digits)


async def test_soda_client_upstream_error_on_5xx():
    client = SodaFMCSAClient(transport=_soda_transport([], status=500))
    with pytest.raises(FMCSAUpstreamError):
        await client.lookup(mc="133655")


async def test_soda_client_dot_path_uses_dot_number_param():
    cap = {}
    client = SodaFMCSAClient(transport=_soda_transport([SODA_ROW_MC], capture=cap))
    c = await client.lookup(dot="264184")
    assert c.dot_number == "264184"
    assert cap["dot"] == "264184" and cap["where"] is None


async def test_soda_client_requires_an_identifier():
    with pytest.raises(ValueError):
        await SodaFMCSAClient().lookup()


# ------------------------------- factory ----------------------------------- #
def _settings(**kw):
    base = dict(tms_host="h", tms_port=1, tms_token="t")
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_factory_returns_stub_when_use_stubs():
    # USE_STUBS wins regardless of source/key.
    assert isinstance(
        get_fmcsa_client(_settings(use_stubs=True, fmcsa_api_key="k", fmcsa_source="qcmobile")),
        StubFMCSAClient,
    )


def test_factory_defaults_to_soda_when_live():
    # no key needed for the default SODA backend
    assert isinstance(get_fmcsa_client(_settings(use_stubs=False)), SodaFMCSAClient)


def test_factory_qcmobile_with_key_returns_live():
    assert isinstance(
        get_fmcsa_client(_settings(use_stubs=False, fmcsa_source="qcmobile", fmcsa_api_key="k")),
        LiveFMCSAClient,
    )


def test_factory_qcmobile_without_key_degrades_to_stub():
    assert isinstance(get_fmcsa_client(_settings(use_stubs=False, fmcsa_source="qcmobile")), StubFMCSAClient)


def test_factory_explicit_stub_source():
    assert isinstance(get_fmcsa_client(_settings(use_stubs=False, fmcsa_source="stub")), StubFMCSAClient)
