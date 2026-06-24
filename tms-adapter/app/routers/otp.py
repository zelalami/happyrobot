"""POST /otp/send and POST /otp/verify.

send resolves the destination from FMCSA SERVER-SIDE (never a caller-supplied phone),
issues a code via OtpStore, and hands the plaintext only to the SMS sender — the
code is NEVER in the response. verify returns a pure outcome (verified|rejected|
locked_out). State is keyed to the server-trusted run_id + bound mc. Always 200 + status.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_fmcsa, get_otp, get_sms, require_bearer
from app.schemas import OtpSendRequest, OtpVerifyRequest
from app.services.otp_store import OtpSendOutcome

router = APIRouter(tags=["otp"], dependencies=[Depends(require_bearer)])
BROKER = "HappyRobot Logistics"


@router.post("/otp/send")
async def otp_send(body: OtpSendRequest, fmcsa=Depends(get_fmcsa), otp=Depends(get_otp), sms=Depends(get_sms)):
    carrier = await fmcsa.lookup(mc=body.mc)  # CarrierNotFound/FMCSAUpstreamError -> handlers
    phone = carrier.registered_phone
    if not phone:
        return {"status": "no_registered_phone"}

    outcome, public_body, code = otp.issue(body.run_id, body.mc)
    if outcome is OtpSendOutcome.RATE_LIMITED:
        return {"status": "rate_limited"}
    if outcome is OtpSendOutcome.MC_MISMATCH:
        return {"status": "mc_mismatch"}

    result = await sms.send(phone, f"Your {BROKER} verification code is {code}. It expires in 5 minutes.")
    return {
        "status": "sent",
        "to_masked": result.to_masked,    # masked destination only
        "channel": result.channel,
        "expires_in": public_body["expires_in"],
        "request_id": public_body["request_id"],
        # NOTE: the code is intentionally absent — it went only to the SMS sender.
    }


@router.post("/otp/verify")
async def otp_verify(body: OtpVerifyRequest, otp=Depends(get_otp)):
    outcome, detail = otp.verify(body.run_id, body.mc, body.code)
    out = {"status": outcome.value}
    if "attempts_remaining" in detail:
        out["attempts_remaining"] = detail["attempts_remaining"]
    return out
