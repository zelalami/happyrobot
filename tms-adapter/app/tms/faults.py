"""TMS wire-fault taxonomy and terminal-line detection.

The legacy TMS never *signals* a fault — the adapter must infer it from socket
behaviour. This module owns the fault enum, the typed error the client/parser
raise, and the strict terminal-line detection used by the read loop.

A `TMSFaultError` is a wire/framing fault (timeout, truncation, garbage). It is
distinct from `TMSError` (a clean `ERR|CODE:..` response) in errors.py.
"""
from __future__ import annotations

from enum import Enum


class TMSFault(str, Enum):
    TIMEOUT = "timeout"              # no complete response within the deadline
    PARTIAL = "partial"             # peer closed before a terminal line
    MALFORMED = "malformed"         # terminal seen but framing/width invalid
    CONNECT_ERROR = "connect_error"  # could not establish the socket


# Wire fault -> HTTP status surfaced by the REST layer.
FAULT_TO_HTTP: dict[TMSFault, int] = {
    TMSFault.TIMEOUT: 504,
    TMSFault.PARTIAL: 502,
    TMSFault.MALFORMED: 502,
    TMSFault.CONNECT_ERROR: 502,
}


class TMSFaultError(Exception):
    """Raised when wire behaviour or framing is faulty (not a clean ERR)."""

    def __init__(self, fault: TMSFault, detail: str = "", raw: bytes = b""):
        self.fault = fault
        self.detail = detail
        self.raw = raw  # token-bearing; redact before logging
        super().__init__(f"{fault.value}: {detail}" if detail else fault.value)

    @property
    def http_status(self) -> int:
        return FAULT_TO_HTTP[self.fault]


_CRLF = b"\r\n"


def complete_lines(buf: bytes, at_eof: bool = False) -> list[bytes]:
    """Lines that are fully delimited.

    A line counts as complete only when followed by CRLF. At EOF the peer's
    close is itself a line boundary, so a trailing non-empty segment also counts.
    The "in-progress" tail after the final CRLF is excluded while streaming.
    """
    parts = buf.split(_CRLF)
    lines = parts[:-1]
    if at_eof and parts and parts[-1]:
        lines = parts
    return lines


def _is_err(line: bytes) -> bool:
    return line == b"ERR" or line.startswith(b"ERR|")


def find_terminal(buf: bytes, at_eof: bool = False) -> str | None:
    """Return 'end' / 'err' if a complete terminal line is present, else None.

    Strict: a terminal only counts at a real line boundary, so a bare
    `END` mid-stream (no trailing CRLF, not yet EOF) does NOT end the read.
    """
    for line in complete_lines(buf, at_eof):
        if line == b"END":
            return "end"
        if _is_err(line):
            return "err"
    return None
