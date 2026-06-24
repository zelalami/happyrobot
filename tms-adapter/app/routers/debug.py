"""GET /debug/outbox — view the stub SMS outbox (the only way to read the OTP code).

This route exists so a full happy-path (including a successful OTP verify) is
drivable over HTTP: the OTP code is CSPRNG and is never logged or returned by
/otp/send, so the stub SMS outbox is the only place to read it back. SMS is
stub-only today (no real provider is wired), so the router is mounted
unconditionally (see create_app) and protected by the same bearer auth as every
other endpoint. A deployment that sends to a real SMS provider would drop this
route — the code would arrive on the carrier's phone instead.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_sms, require_bearer

router = APIRouter(tags=["debug"], dependencies=[Depends(require_bearer)])


@router.get("/debug/outbox")
async def debug_outbox(sms=Depends(get_sms)):
    """Return every stub SMS sent this process (newest last). Bodies include the
    OTP code — acceptable because SMS is stub-only and the route is bearer-protected;
    it would be removed once a real SMS provider is wired."""
    outbox = getattr(sms, "outbox", [])
    return {
        "status": "ok",
        "messages": [{"to": m.to, "body": m.body} for m in outbox],
    }
