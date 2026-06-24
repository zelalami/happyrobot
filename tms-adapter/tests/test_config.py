import pytest
from pydantic import ValidationError

from app.config import Settings

BASE = dict(tms_host="h", tms_port=17159, tms_token="secret-token")


def test_loads_required_fields_and_defaults():
    s = Settings(_env_file=None, **BASE)
    assert s.tms_host == "h" and s.tms_port == 17159
    assert s.use_stubs is True  # stub-by-default
    assert s.negotiation_max_rounds == 3
    assert s.otp_ttl_s == 300 and s.otp_max_attempts == 3
    assert s.tms_deadline_s == 8.0


def test_tms_token_required():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, tms_host="h", tms_port=1)


def test_secrets_never_appear_in_repr():
    s = Settings(_env_file=None, tms_token="secret-token", tms_host="h", tms_port=1,
                 fmcsa_api_key="fmcsa-secret")
    text = repr(s)
    assert "secret-token" not in text and "fmcsa-secret" not in text
    # ...but the value is still retrievable at the point of use.
    assert s.tms_token.get_secret_value() == "secret-token"


def test_use_stubs_parses_env_string(monkeypatch):
    monkeypatch.setenv("TMS_HOST", "h")
    monkeypatch.setenv("TMS_PORT", "1")
    monkeypatch.setenv("TMS_TOKEN", "t")
    monkeypatch.setenv("USE_STUBS", "false")
    s = Settings(_env_file=None)
    assert s.use_stubs is False


def test_fmcsa_source_defaults_to_soda():
    assert Settings(_env_file=None, **BASE).fmcsa_source == "soda"


def test_fmcsa_source_normalized_and_validated():
    assert Settings(_env_file=None, fmcsa_source="QCMobile", **BASE).fmcsa_source == "qcmobile"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, fmcsa_source="nope", **BASE)
