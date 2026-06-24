"""Server-side OTP state — OTP confirmed mid-call; resists social engineering.

Trust model (the corrections that make this hard to bypass):
- State is keyed ONLY by the server-trusted run_id. A caller-supplied
  request_id / round / "verified" / "skip" field is never trusted or honored.
- Each run binds the mc established at FMCSA time; a verify or resend with a
  DIFFERENT mc cannot escape lockout or allocate a fresh attempt pool.
- The verify attempt budget is STICKY across resends: a resend NEVER refills
  it. Once locked, the run stays locked even after a new code is sent.
- Codes are 6-digit CSPRNG, stored HASHED with a per-process pepper and compared
  in constant time; the plaintext is returned ONCE to the caller (to hand to the
  SMS sender) and is NEVER stored, logged, or placed in the workflow-facing body.
- A verified entry is single-use (no replay). There is no "skip OTP" path.

The registered-number resolution + masking and the actual SMS send live in the
router/SMS service (the destination is the broker-side record for the MC,
never a caller-supplied phone) — this module owns only the code lifecycle.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum


class OtpOutcome(str, Enum):
    VERIFIED = "verified"
    REJECTED = "rejected"       # wrong code, attempts remain
    LOCKED_OUT = "locked_out"   # attempts exhausted / expired / consumed / mc mismatch / no entry


class OtpSendOutcome(str, Enum):
    SENT = "sent"
    RATE_LIMITED = "rate_limited"   # resend budget exhausted
    MC_MISMATCH = "mc_mismatch"     # run already bound to a different mc


@dataclass
class _Entry:
    code_hash: str
    mc: str
    expires_at: float
    attempts_remaining: int
    locked: bool = False
    verified: bool = False
    send_times: list[float] = field(default_factory=list)


def _default_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"  # 6-digit, zero-padded, CSPRNG


class OtpStore:
    def __init__(
        self,
        *,
        ttl_s: int = 300,
        max_attempts: int = 3,
        resend_max: int = 3,
        resend_window_s: int = 900,
        clock=time.monotonic,
        code_gen=_default_code,
    ):
        self._ttl_s = ttl_s
        self._max_attempts = max_attempts
        self._resend_max = resend_max
        self._resend_window_s = resend_window_s
        self._clock = clock
        self._code_gen = code_gen
        self._pepper = secrets.token_bytes(32)        # per-process; hashes never leave the process
        self._entries: dict[str, _Entry] = {}

    def _hash(self, code: str) -> str:
        return hmac.new(self._pepper, str(code).encode("ascii"), hashlib.sha256).hexdigest()

    def issue(self, run_id: str, mc: str) -> tuple[OtpSendOutcome, dict, str | None]:
        """Generate a code for (run_id, mc), preserving any existing attempt budget.

        Returns ``(outcome, public_body, code)``. The plaintext ``code`` is a SEPARATE
        return value handed straight to the SMS sender; ``public_body`` is the only thing
        safe to surface to the workflow (it never contains the code). On a non-SENT
        outcome ``code`` is None.
        """
        run_id, mc = str(run_id), str(mc)
        now = self._clock()
        entry = self._entries.get(run_id)

        if entry is not None and entry.mc != mc:
            return OtpSendOutcome.MC_MISMATCH, {"reason": "mc_bound_to_run"}, None

        recent = [t for t in entry.send_times if now - t < self._resend_window_s] if entry else []
        if len(recent) >= self._resend_max:
            return OtpSendOutcome.RATE_LIMITED, {"reason": "resend_rate_limited"}, None

        # A resend NEVER refills the budget. Fresh budget only on the FIRST send for this
        # run. Carry the lock forward ONLY when it is a true attempt-exhaustion lock — a lock
        # set by a transient TTL expiry must NOT survive a legitimate resend (else an
        # expired-then-verified run would deadlock the carrier).
        if entry is None:
            attempts, locked = self._max_attempts, False
        else:
            attempts = entry.attempts_remaining
            locked = entry.locked and entry.attempts_remaining <= 0

        code = self._code_gen()
        self._entries[run_id] = _Entry(
            code_hash=self._hash(code), mc=mc, expires_at=now + self._ttl_s,
            attempts_remaining=attempts, locked=locked, verified=False,
            send_times=recent + [now],
        )
        public_body = {
            "request_id": "otp_" + secrets.token_hex(8),  # informational only; verify keys on run_id
            "expires_in": self._ttl_s,
        }
        return OtpSendOutcome.SENT, public_body, code

    def verify(self, run_id: str, mc: str, code: str) -> tuple[OtpOutcome, dict]:
        run_id, mc = str(run_id), str(mc)
        entry = self._entries.get(run_id)
        if entry is None:
            return OtpOutcome.LOCKED_OUT, {"reason": "no_active_code"}
        if entry.mc != mc:                                 # cross-mc / mc-swap -> fail closed
            return OtpOutcome.LOCKED_OUT, {"reason": "mc_mismatch"}
        if entry.verified:                                 # single-use: no replay (most specific)
            return OtpOutcome.LOCKED_OUT, {"reason": "already_verified"}
        if entry.locked:
            return OtpOutcome.LOCKED_OUT, {"reason": "locked_out"}
        if self._clock() >= entry.expires_at:
            entry.locked = True
            return OtpOutcome.LOCKED_OUT, {"reason": "expired"}

        if hmac.compare_digest(entry.code_hash, self._hash(code)):
            entry.verified = True
            entry.locked = True                            # consume so the code can't be replayed
            return OtpOutcome.VERIFIED, {}

        entry.attempts_remaining -= 1
        if entry.attempts_remaining <= 0:
            entry.locked = True
            return OtpOutcome.LOCKED_OUT, {"reason": "locked_out", "attempts_remaining": 0}
        return OtpOutcome.REJECTED, {"reason": "incorrect", "attempts_remaining": entry.attempts_remaining}
