"""POST /offers/evaluate (the deterministic ceiling decision) and POST /offers/log.

evaluate goes through NegotiationStore, which OWNS the round counter + prior_counter
keyed to (run_id, load_id) — the caller cannot supply or reset them (closes the
binary-search leak). max_buy/posted_rate are read from the server-side load-economics
cache (seeded by /loads/get; fetched here if absent) and NEVER returned. Always 200 + status.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_audit, get_commands, get_load_economics, get_negotiation, require_bearer
from app.logging import get_logger
from app.schemas import EvaluateOfferRequest, LogOfferRequest

router = APIRouter(tags=["offers"], dependencies=[Depends(require_bearer)])
_log = get_logger("offers")


async def _economics(load_id: str, economics: dict, commands) -> dict:
    key = str(load_id).strip()
    if key not in economics:
        rec = await commands.load_get(key)  # TMSError/TMSFaultError -> handlers (not_found/unavailable)
        economics[key] = {"max_buy": rec.get("MAX_BUY"), "posted_rate": rec.get("RATE")}
    return economics[key]


@router.post("/offers/evaluate")
async def evaluate_offer_endpoint(body: EvaluateOfferRequest, commands=Depends(get_commands),
                                  negotiation=Depends(get_negotiation),
                                  economics: dict = Depends(get_load_economics)):
    econ = await _economics(body.load_id, economics, commands)
    try:
        d = negotiation.evaluate(body.run_id, body.load_id, body.carrier_offer,
                                 econ["max_buy"], econ["posted_rate"])
    except ValueError:
        return {"status": "invalid_request", "error": "offer out of range"}
    # CeilingSanityError -> global handler -> {status: ceiling_error}.
    out = {
        "status": "ok", "decision": d.decision, "round": d.round,
        "max_rounds": d.max_rounds, "rounds_remaining": d.rounds_remaining,
        "ceiling_available": d.ceiling_available,
    }
    if d.suggested_counter is not None:
        out["suggested_counter"] = d.suggested_counter
    if d.agreed_rate is not None:
        out["agreed_rate"] = d.agreed_rate
    if d.reason:
        out["reason"] = d.reason
    # Log only non-secret signals (decision + round) — NEVER an offer-vs-ceiling delta.
    _log.info("offer_evaluated", load_id=body.load_id, decision=d.decision, round=d.round)
    return out


@router.post("/offers/log")
async def log_offer_endpoint(body: LogOfferRequest, audit: list = Depends(get_audit)):
    audit.append({
        "run_id": body.run_id, "load_id": body.load_id,
        "carrier_offer": body.carrier_offer, "mc_number": body.mc_number, "notes": body.notes,
    })
    return {"status": "logged"}
