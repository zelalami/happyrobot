"""High-level TMS commands with the idempotency & retry policy.

Reads (LOAD_QUERY / LOAD_GET / DEBUG_ECHO) are idempotent -> bounded retries on
transient wire faults (TIMEOUT / PARTIAL / MALFORMED) and on retryable TMS codes
(SERVER_ERROR). Deterministic ERRs (NOT_FOUND, INVALID_RATE, ...) never retry.

LOAD_BOOK is NON-idempotent and is handled "verify, don't blindly retry":
an ambiguous BOOK (timeout/partial/malformed, or a clean reply with no
BOOKING_REF, or SERVER_ERROR) is NEVER resent without first verifying via a
LOAD_GET. At most ONE resend, and only when the verify still shows the load OPEN.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import anyio

from app.tms.client import TMSClient
from app.tms.errors import TMSError
from app.tms.faults import TMSFaultError
from app.tms.framing import DecodedResponse, decode_response

DEFAULT_BACKOFF = (0.25, 0.75)  # seconds between read attempts (+/- jitter)


@dataclass
class BookingResult:
    status: str                       # "booked" | "already_booked" | "ambiguous"
    booking_ref: str | None = None
    confirmed: bool = False           # True only on a clean BOOKED record with a ref
    note: str | None = None


def _booking_ref(records: list[dict[str, Any]]) -> str | None:
    for r in records:
        ref = r.get("BOOKING_REF")
        if ref:
            return ref
    return None


class TMSCommands:
    def __init__(
        self,
        client: TMSClient,
        *,
        read_attempts: int = 3,
        backoff: tuple[float, ...] = DEFAULT_BACKOFF,
        jitter: bool = True,
    ):
        self.client = client
        self.read_attempts = read_attempts
        self.backoff = backoff
        self.jitter = jitter

    # ----------------------------- reads ----------------------------------- #
    async def _sleep_backoff(self, attempt: int) -> None:
        base = self.backoff[attempt] if attempt < len(self.backoff) else self.backoff[-1]
        if self.jitter and base > 0:
            base *= 1 + random.uniform(-0.5, 0.5)
        if base > 0:
            await anyio.sleep(base)

    async def _read(self, cmd: str, fields: dict[str, Any] | None = None) -> DecodedResponse:
        # decode_response returns a clean ERR in `.error` (it does not raise), so a
        # retryable SERVER_ERROR is handled here alongside wire faults; the caller
        # raises any non-retryable `.error` it gets back.
        last: Exception | None = None
        for attempt in range(self.read_attempts):
            try:
                decoded = decode_response(await self.client.request(cmd, fields))
            except TMSFaultError as e:
                last = e
            else:
                if decoded.error is not None and decoded.error.retryable:
                    last = decoded.error
                else:
                    return decoded
            if attempt < self.read_attempts - 1:
                await self._sleep_backoff(attempt)
        assert last is not None
        raise last

    async def debug_echo(self, msg: str = "HELLO") -> dict[str, Any]:
        """DEBUG_ECHO is fault-exempt and leads with a bare ECHO marker, so it is
        parsed here rather than through the strict record decoder."""
        text = (await self.client.request("DEBUG_ECHO", {"MSG": msg})).decode("ascii", "replace")
        fields_parsed: int | None = None
        for tok in text.replace("\r\n", "|").split("|"):
            k, _, v = tok.partition(":")
            if k == "FIELDS_PARSED":
                try:
                    fields_parsed = int(v)
                except ValueError:
                    pass
        return {"auth_ok": "AUTH:OK" in text, "fields_parsed": fields_parsed}

    async def load_query(self, **filters: Any) -> list[dict[str, Any]]:
        decoded = await self._read("LOAD_QUERY", filters)
        if decoded.error is not None:
            raise decoded.error
        return decoded.records

    async def load_get(self, load_id: str) -> dict[str, Any]:
        lid = str(load_id).strip()  # IDs are space-padded to width 12 -> strip or NOT_FOUND
        decoded = await self._read("LOAD_GET", {"LOAD_ID": lid})
        if decoded.error is not None:
            raise decoded.error
        if not decoded.records:
            raise TMSError("NOT_FOUND", "empty LOAD_GET response")
        return decoded.records[0]

    # --------------------------- booking ----------------------------------- #
    async def load_book(self, load_id: str, mc_number: str, agreed_rate: int) -> BookingResult:
        return await self._book(str(load_id).strip(), mc_number, agreed_rate, resent=False)

    async def _book(self, lid: str, mc: str, rate: int, *, resent: bool) -> BookingResult:
        fields = {"LOAD_ID": lid, "MC_NUM": mc, "AGREED_RATE": rate}
        try:
            decoded = decode_response(await self.client.request("LOAD_BOOK", fields))
        except TMSFaultError:
            # timeout / partial / malformed -> AMBIGUOUS. Do not resend; verify.
            return await self._verify(lid, mc, rate, resent=resent)

        if decoded.error is not None:
            code = decoded.error.code
            if code == "ALREADY_BOOKED":
                return BookingResult("already_booked", note="TMS reported ALREADY_BOOKED")
            if code == "SERVER_ERROR":
                return await self._verify(lid, mc, rate, resent=resent)
            raise decoded.error  # INVALID_RATE / UNKNOWN_LOAD / MISSING_FIELD -> deterministic

        ref = _booking_ref(decoded.records)
        if ref:
            return BookingResult("booked", booking_ref=ref, confirmed=True)
        # clean reply but no ref -> ambiguous; verify before any resend.
        return await self._verify(lid, mc, rate, resent=resent)

    async def _verify(self, lid: str, mc: str, rate: int, *, resent: bool) -> BookingResult:
        try:
            rec = await self.load_get(lid)  # idempotent read, with its own retries
        except TMSError as e:
            if e.code in ("NOT_FOUND", "UNKNOWN_LOAD"):
                return BookingResult("ambiguous", note="verify: load not found")
            raise
        except TMSFaultError:
            return BookingResult("ambiguous", note="verify: read failed")

        status = (rec.get("STATUS") or "").upper()
        if status and status != "OPEN":
            # A status read cannot prove WE booked it -> confirmed stays False.
            return BookingResult(
                "booked", booking_ref=rec.get("BOOKING_REF"), confirmed=False,
                note="verified via status",
            )
        # Still OPEN: the BOOK did not commit.
        if resent:
            return BookingResult("ambiguous", note="still open after one resend")
        return await self._book(lid, mc, rate, resent=True)  # the single allowed resend
