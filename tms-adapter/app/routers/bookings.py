"""POST /bookings — LOAD_BOOK behind a server-side guard.

Two independent gates BEFORE we ever send LOAD_BOOK:
  1. The agreed_rate must equal a rate the adapter itself recorded as ACCEPTED for this
     (run_id, load_id) — not merely "<= ceiling". A rate that was never accepted
     (including any over-ceiling counter, which never accepts) is refused.
  2. Defense-in-depth: agreed_rate must be <= max_buy (read server-side; never revealed).
Then the verify-don't-retry LOAD_BOOK from the TMS client. Always 200 + status.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_commands, get_load_economics, get_negotiation, require_bearer
from app.logging import get_logger
from app.schemas import BookingRequest

router = APIRouter(tags=["bookings"], dependencies=[Depends(require_bearer)])
_log = get_logger("bookings")


async def _max_buy(load_id: str, economics: dict, commands):
    key = str(load_id).strip()
    if key not in economics:
        rec = await commands.load_get(key)  # raises -> handlers
        economics[key] = {"max_buy": rec.get("MAX_BUY"), "posted_rate": rec.get("RATE")}
    return economics[key]["max_buy"]


@router.post("/bookings")
async def create_booking(body: BookingRequest, commands=Depends(get_commands),
                         negotiation=Depends(get_negotiation),
                         economics: dict = Depends(get_load_economics)):
    max_buy = await _max_buy(body.load_id, economics, commands)
    if max_buy is None:
        return {"status": "ceiling_unavailable"}  # fail closed; cannot enforce the ceiling

    # (1) Only book a rate the adapter actually accepted for this run+load.
    accepted = negotiation.accepted_rate(body.run_id, body.load_id)
    if accepted is None or body.agreed_rate != accepted:
        _log.warning("booking_rate_not_accepted", load_id=body.load_id)
        return {"status": "rate_not_accepted"}

    # (2) Defense-in-depth: never exceed the ceiling (without revealing it).
    if body.agreed_rate > max_buy:
        return {"status": "rate_exceeds_ceiling"}

    result = await commands.load_book(body.load_id, body.mc_number, body.agreed_rate)
    if result.status == "booked":
        return {"status": "booked", "booking_ref": result.booking_ref,
                "agreed_rate": body.agreed_rate, "confirmed": result.confirmed}
    if result.status == "already_booked":
        return {"status": "already_booked"}
    return {"status": "booking_ambiguous", "action": "escalate_to_human"}
