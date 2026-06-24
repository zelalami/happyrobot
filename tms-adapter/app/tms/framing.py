"""Frame encoder and response decoder for the legacy TMS line protocol.

Request:  CMD:<cmd>|AUTH:<token>|KEY:VALUE|...  CRLF-terminated, ASCII, <=4096B.
Response: CRLF-delimited lines — record lines (KEY:VALUE|...), a bare `END`
          terminator, or a single `ERR|CODE:..|MSG:..` line. Values are
          space-padded and MAY contain ':' (split on the FIRST colon only);
          they may not contain '|' or CR/LF (enforced at encode time).

`decode_response()` is for LOAD_QUERY / LOAD_GET / LOAD_BOOK record responses.
It assumes a terminal is present (the read loop guarantees this) and is
deliberately strict: a token that is not KEY:VALUE, any content after END, an
over-width value, or a non-ASCII byte is a MALFORMED fault — never a partial
success. A buffer with neither END nor ERR is reported as PARTIAL.

Note: DEBUG_ECHO replies (`ECHO|AUTH:OK|FIELDS_PARSED:n|...`) lead with a bare
`ECHO` marker and are parsed separately in commands.py, not here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.tms.errors import TMSError
from app.tms.faults import TMSFault, TMSFaultError
from app.tms.widths import normalize_record

MAX_FRAME = 4096


def encode_request(cmd: str, token: str, fields: dict[str, Any] | None = None) -> bytes:
    """Build one CRLF-terminated request frame. CMD first, AUTH second, then fields.

    Rejects illegal characters at encode time rather than sending a frame the TMS
    would answer with MALFORMED.
    """
    if not cmd or any(c in cmd for c in ("|", ":", "\r", "\n")):
        raise ValueError(f"illegal command {cmd!r}")
    pairs = [f"CMD:{cmd}", f"AUTH:{token}"]
    for k, v in (fields or {}).items():
        key = k.upper()
        if any(c in key for c in ("|", ":", "\r", "\n")):
            raise ValueError(f"illegal char in field name {k!r}")
        val = str(v)
        if any(c in val for c in ("|", "\r", "\n")):
            raise ValueError(f"illegal char in field {k}")
        pairs.append(f"{key}:{val}")
    text = "|".join(pairs) + "\r\n"
    try:
        frame = text.encode("ascii")
    except UnicodeEncodeError as e:
        raise ValueError("frame contains non-ASCII bytes") from e
    if len(frame) > MAX_FRAME:
        raise ValueError(f"frame exceeds {MAX_FRAME}B")
    return frame


@dataclass
class DecodedResponse:
    records: list[dict[str, Any]] = field(default_factory=list)
    error: TMSError | None = None
    seen_end: bool = False


def _parse_record_line(line: str) -> dict[str, str]:
    raw: dict[str, str] = {}
    for tok in line.split("|"):
        if ":" not in tok:
            raise TMSFaultError(TMSFault.MALFORMED, f"token without ':' -> {tok!r}")
        k, _, v = tok.partition(":")  # first colon only; values may contain ':'
        if k == "":
            raise TMSFaultError(TMSFault.MALFORMED, f"empty key in {tok!r}")
        raw[k] = v
    return raw


def _parse_err_line(line: str) -> TMSError:
    code, msg = "", ""
    for tok in line.split("|")[1:]:  # skip the leading 'ERR' marker
        k, _, v = tok.partition(":")
        if k == "CODE":
            code = v
        elif k == "MSG":
            msg = v
    return TMSError(code or "UNKNOWN", msg)


def decode_response(buf: bytes) -> DecodedResponse:
    try:
        text = buf.decode("ascii")
    except UnicodeDecodeError as e:
        raise TMSFaultError(TMSFault.MALFORMED, "non-ASCII byte in response", buf) from e

    out = DecodedResponse()
    for line in text.split("\r\n"):
        if line == "":
            continue  # trailing/interstitial CRLF padding
        if out.seen_end:
            raise TMSFaultError(TMSFault.MALFORMED, f"content after END: {line!r}", buf)
        if line == "END":
            out.seen_end = True
            continue
        if line == "ERR" or line.startswith("ERR|"):
            out.error = _parse_err_line(line)
            continue
        out.records.append(normalize_record(_parse_record_line(line)))

    if out.error is None and not out.seen_end:
        raise TMSFaultError(TMSFault.PARTIAL, "no END terminator", buf)
    return out
