"""SMS delivery for OTP codes.

STUB-ONLY for now (decision 2026-06-22): a real provider (Twilio) is deferred
until the end-to-end workflow is proven. The interface + a deterministic stub are
in place so the OTP router never changes when a real provider lands. The stub
keeps an in-memory `outbox` so tests and the demo can assert a message went out
without sending a real text.

The OTP code itself is passed in by the caller (from OtpStore.issue's separate
secret channel) and is NEVER logged here; only a masked destination is surfaced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.services.phone import mask_phone


@dataclass
class SmsResult:
    sent: bool
    to_masked: str | None
    channel: str = "sms"


@dataclass
class SentMessage:
    to: str
    body: str


class SmsSender(Protocol):
    async def send(self, to: str, body: str) -> SmsResult: ...


class StubSmsSender:
    """Records messages instead of sending; deterministic, no external account."""

    def __init__(self):
        self.outbox: list[SentMessage] = []

    async def send(self, to: str, body: str) -> SmsResult:
        self.outbox.append(SentMessage(to=to, body=body))
        return SmsResult(sent=True, to_masked=mask_phone(to), channel="stub")


class TwilioSmsSender:
    """Seam for the real provider — intentionally NOT implemented yet (stub-only policy)."""

    def __init__(self, *args, **kwargs):
        self._cfg = (args, kwargs)

    async def send(self, to: str, body: str) -> SmsResult:  # pragma: no cover - deferred
        raise NotImplementedError(
            "Twilio SMS integration is deferred; SMS is stub-only for now (set USE_STUBS=true)."
        )


# Single shared stub instance so the OTP router and a /debug view see the same outbox.
_STUB = StubSmsSender()


def get_sms_sender(settings=None) -> SmsSender:
    """SMS is stub-only regardless of USE_STUBS — Twilio integration is deferred.

    When a real provider is wired up, branch here on settings.use_stubs.
    """
    return _STUB
