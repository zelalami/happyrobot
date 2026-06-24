"""POST /carriers/find — FMCSA authority check.

Returns 200 + a status field for every business outcome (found / not_found /
fmcsa_unavailable / invalid_request) so the workflow run stays COMPLETED.
The carrier's raw registered phone is never returned — only a masked form.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_fmcsa, require_bearer
from app.schemas import FindCarrierRequest

router = APIRouter(tags=["carriers"], dependencies=[Depends(require_bearer)])


@router.post("/carriers/find")
async def find_carrier(body: FindCarrierRequest, fmcsa=Depends(get_fmcsa)):
    if not (body.mc or body.dot):
        return {"status": "invalid_request", "error": "mc or dot required"}
    carrier = await fmcsa.lookup(mc=body.mc, dot=body.dot)  # CarrierNotFound/FMCSAUpstreamError -> handlers
    return {"status": "found", "carrier": carrier.to_bridge()}
