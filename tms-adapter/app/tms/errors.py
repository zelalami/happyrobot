"""Clean ERR responses from the TMS and their REST/retry mapping.

A `TMSError` is a *clean* protocol error line (`ERR|CODE:..|MSG:..`) — distinct
from a `TMSFaultError` (wire/framing fault) in faults.py. The code drives both
the HTTP status surfaced to callers and whether a retry could ever help.
"""
from __future__ import annotations

DEFAULT_TMS_HTTP = 502

TMS_CODE_TO_HTTP: dict[str, int] = {
    "AUTH_FAILED": 502,    # our credential is bad, not the caller's
    "UNKNOWN_CMD": 500,
    "MISSING_FIELD": 400,
    "UNKNOWN_LOAD": 404,
    "NOT_FOUND": 404,      # undocumented but REAL: LOAD_GET miss
    "ALREADY_BOOKED": 409,
    "INVALID_RATE": 422,
    "SERVER_ERROR": 502,
}

# Deterministic codes: an identical retry returns the identical answer.
NON_RETRYABLE_CODES = frozenset({
    "AUTH_FAILED", "UNKNOWN_CMD", "MISSING_FIELD",
    "UNKNOWN_LOAD", "NOT_FOUND", "INVALID_RATE", "ALREADY_BOOKED",
})
# Transient TMS-reported errors worth one bounded retry on idempotent reads.
RETRYABLE_CODES = frozenset({"SERVER_ERROR"})


class TMSError(Exception):
    def __init__(self, code: str, msg: str = ""):
        self.code = code
        self.msg = msg
        super().__init__(f"{code}: {msg}" if msg else code)

    @property
    def http_status(self) -> int:
        return TMS_CODE_TO_HTTP.get(self.code, DEFAULT_TMS_HTTP)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES
