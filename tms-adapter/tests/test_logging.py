from app.logging import make_redactor


def test_redacts_a_long_secret_value():
    p = make_redactor(["supersecret-bearer-token-1234"])
    out = p(None, None, {"event": "x", "frame": "AUTH:supersecret-bearer-token-1234|CMD:Y"})
    assert "supersecret-bearer-token-1234" not in out["frame"]
    assert "***REDACTED***" in out["frame"]


def test_does_not_redact_trivially_short_value():
    # A 1-char "secret" must not scrub every occurrence of that char.
    p = make_redactor(["t"])
    out = p(None, None, {"event": "counter", "decision": "accept"})
    assert out == {"event": "counter", "decision": "accept"}


def test_redacts_auth_substring_even_with_no_known_secret():
    p = make_redactor([])
    out = p(None, None, {"frame": "CMD:LOAD_GET|AUTH:abc123def456|LOAD_ID:LD1"})
    assert "abc123def456" not in out["frame"]
    assert "AUTH:***REDACTED***" in out["frame"]
