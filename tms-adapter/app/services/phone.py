"""Phone normalisation + masking shared by the FMCSA and SMS services.

The OTP destination is always the SERVER-resolved registered number; the
workflow only ever sees a MASKED form, never the full number, and never supplies
one.
"""
from __future__ import annotations

import re


def normalize_phone(raw: str | None) -> str | None:
    """Best-effort E.164 from a free-form US phone string. None if unusable."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if len(digits) >= 8:               # best effort for already-international numbers
        return "+" + digits
    return None


def mask_phone(e164: str | None) -> str | None:
    """+15550133655 -> +1******3655 (keep '+1' and the last 4, mask the middle)."""
    if not e164:
        return None
    prefix = e164[:2] if e164.startswith("+") else ""
    last4 = e164[-4:]
    middle = max(0, len(e164) - len(prefix) - 4)
    return f"{prefix}{'*' * middle}{last4}"
