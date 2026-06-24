"""OTP-store tests — encodes the attack surface.

Central guarantees: 3 attempts total (sticky across resends), keyed to a
server-trusted run_id + bound mc, single-use, code never stored in plaintext.
"""
import pytest

from app.services.otp_store import OtpOutcome, OtpSendOutcome, OtpStore

CODE = "424242"


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _store(**kw) -> OtpStore:
    opts = dict(ttl_s=300, max_attempts=3, resend_max=3, code_gen=lambda: CODE)
    opts.update(kw)
    return OtpStore(**opts)


def _issue(store, run="run1", mc="MC1"):
    return store.issue(run, mc)


# ------------------------------ happy path --------------------------------- #
def test_issue_then_correct_code_verifies():
    s = _store()
    outcome, _, code = _issue(s)
    assert outcome is OtpSendOutcome.SENT and code == CODE
    assert s.verify("run1", "MC1", CODE)[0] is OtpOutcome.VERIFIED


def test_public_body_never_contains_the_code():
    # The plaintext is a SEPARATE return value; the workflow-facing body must not carry it.
    s = _store()
    _, public_body, code = _issue(s)
    assert "code" not in public_body
    assert CODE not in str(public_body)
    assert code == CODE  # ...but it IS available on the separate channel for the SMS sender


def test_code_stored_hashed_not_plaintext():
    s = _store()
    _issue(s)
    stored = s._entries["run1"].code_hash
    assert stored != CODE and len(stored) == 64  # sha256 hex


def test_default_code_is_six_digit_csprng():
    s = OtpStore()  # real generator
    for i in range(50):
        _, _, code = s.issue(f"run{i}", "MC1")
        assert len(code) == 6 and code.isdigit()


# --------------------------- attempt counting ------------------------------ #
def test_three_wrong_attempts_then_locked():
    s = _store()
    _issue(s)
    assert s.verify("run1", "MC1", "000000") == (OtpOutcome.REJECTED, {"reason": "incorrect", "attempts_remaining": 2})
    assert s.verify("run1", "MC1", "000000")[1]["attempts_remaining"] == 1
    out, detail = s.verify("run1", "MC1", "000000")
    assert out is OtpOutcome.LOCKED_OUT and detail["attempts_remaining"] == 0


def test_correct_code_on_third_attempt_still_verifies():
    s = _store()
    _issue(s)
    s.verify("run1", "MC1", "000000")
    s.verify("run1", "MC1", "000000")
    assert s.verify("run1", "MC1", CODE)[0] is OtpOutcome.VERIFIED


def test_wrong_codes_give_uniform_feedback_no_partial_match():
    # A code sharing a prefix with the real one must look identical to a random wrong one.
    s = _store()
    _issue(s)
    a = s.verify("run1", "MC1", "424200")  # shares prefix
    b = s.verify("run1", "MC1", "999999")  # random
    assert a[0] is b[0] is OtpOutcome.REJECTED
    assert a[1]["reason"] == b[1]["reason"] == "incorrect"


# ------------------------ sticky lockout / resend ------------------------- #
def test_resend_does_not_refill_attempt_budget():
    s = _store()
    _issue(s)
    for _ in range(3):
        s.verify("run1", "MC1", "000000")  # exhaust -> locked
    assert s.verify("run1", "MC1", CODE)[0] is OtpOutcome.LOCKED_OUT
    # Resend mints a NEW code but must NOT refill the budget.
    s.issue("run1", "MC1")
    assert s.verify("run1", "MC1", CODE)[0] is OtpOutcome.LOCKED_OUT


def test_resend_rate_limited_after_max():
    s = _store(resend_max=3)
    assert s.issue("run1", "MC1")[0] is OtpSendOutcome.SENT
    assert s.issue("run1", "MC1")[0] is OtpSendOutcome.SENT
    assert s.issue("run1", "MC1")[0] is OtpSendOutcome.SENT
    assert s.issue("run1", "MC1")[0] is OtpSendOutcome.RATE_LIMITED


# ------------------------------ TTL expiry --------------------------------- #
def test_correct_code_just_before_ttl_verifies():
    clock = FakeClock()
    s = _store(clock=clock)
    _issue(s)
    clock.advance(299)
    assert s.verify("run1", "MC1", CODE)[0] is OtpOutcome.VERIFIED


def test_correct_code_after_ttl_is_locked():
    clock = FakeClock()
    s = _store(clock=clock)
    _issue(s)
    clock.advance(301)
    out, detail = s.verify("run1", "MC1", CODE)
    assert out is OtpOutcome.LOCKED_OUT and detail["reason"] == "expired"


def test_expired_then_resend_recovers_not_permanently_locked():
    # A transient TTL-expiry lock must NOT survive a legitimate resend (availability):
    # only a true attempt-exhaustion lock is sticky.
    clock = FakeClock()
    s = _store(clock=clock)
    _issue(s)
    clock.advance(301)
    assert s.verify("run1", "MC1", CODE)[0] is OtpOutcome.LOCKED_OUT  # expired -> sets locked
    _issue(s)  # resend mints a fresh code; budget never exhausted, so lock must clear
    assert s.verify("run1", "MC1", CODE)[0] is OtpOutcome.VERIFIED


# --------------------------- single-use / replay --------------------------- #
def test_verified_code_cannot_be_replayed():
    s = _store()
    _issue(s)
    assert s.verify("run1", "MC1", CODE)[0] is OtpOutcome.VERIFIED
    out, detail = s.verify("run1", "MC1", CODE)
    assert out is OtpOutcome.LOCKED_OUT and detail["reason"] == "already_verified"


# ------------------------- binding: run_id + mc --------------------------- #
def test_verify_before_send_fails_closed():
    s = _store()
    assert s.verify("never", "MC1", CODE)[0] is OtpOutcome.LOCKED_OUT


def test_code_does_not_verify_for_a_different_run():
    s = _store()
    s.issue("runA", "MC1")
    assert s.verify("runB", "MC1", CODE)[0] is OtpOutcome.LOCKED_OUT


def test_code_does_not_verify_for_a_different_mc():
    s = _store()
    s.issue("run1", "MC1")
    assert s.verify("run1", "MC2", CODE)[0] is OtpOutcome.LOCKED_OUT


def test_mc_swap_cannot_escape_lockout_or_get_fresh_budget():
    s = _store()
    s.issue("run1", "MC1")
    for _ in range(3):
        s.verify("run1", "MC1", "000000")  # lock (run1, MC1)
    # Attacker tries to rebind the run to a new MC to mint a fresh pool.
    assert s.issue("run1", "MC2")[0] is OtpSendOutcome.MC_MISMATCH
    assert s.verify("run1", "MC2", CODE)[0] is OtpOutcome.LOCKED_OUT
    assert s.verify("run1", "MC1", CODE)[0] is OtpOutcome.LOCKED_OUT


# ----------------------------- no bypass ----------------------------------- #
def test_verify_signature_has_no_skip_or_force_path():
    import inspect
    params = set(inspect.signature(OtpStore.verify).parameters)
    assert params == {"self", "run_id", "mc", "code"}  # no skip/force/verified field honored
