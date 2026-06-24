"""Liveness + readiness. These are NOT workflow tools, so they use real HTTP codes
(200 / 503), unlike the tool endpoints which always return 200 + a status field.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.deps import get_commands
from app.tms.faults import TMSFaultError

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    """Process liveness — no TMS call."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(commands=Depends(get_commands)):
    """Readiness — fires DEBUG_ECHO (fault-exempt) to confirm the encoder + TMS reachability."""
    try:
        echo = await commands.debug_echo()
    except (TMSFaultError, OSError, Exception):  # noqa: BLE001 - readiness must never raise
        return JSONResponse(status_code=503, content={"status": "not_ready", "tms": "unreachable"})
    if echo.get("auth_ok"):
        return {"status": "ready", "tms": "reachable", "fields_parsed": echo.get("fields_parsed")}
    return JSONResponse(status_code=503, content={"status": "not_ready", "tms": "auth_failed"})
