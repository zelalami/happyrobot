"""FastAPI app factory for the TMS adapter.

Wiring: lifespan builds the shared singletons onto app.state; a middleware binds a
request id; and exception handlers translate the domain exceptions into HTTP 200 +
a `status` field so a tool Webhook never marks the HappyRobot run FAILED.
Genuine bugs still surface as 500 (Webhook nodes set "Ignore 5XX" as the net).
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.deps import require_bearer  # noqa: F401 (re-exported for tests/clarity)
from app.logging import configure_logging, get_logger
from app.routers import bookings, carriers, debug, health, loads, offers, otp
from app.services.ceiling import CeilingSanityError, NegotiationStore
from app.services.fmcsa import CarrierNotFound, FMCSAUpstreamError, get_fmcsa_client
from app.services.otp_store import OtpStore
from app.services.sms import get_sms_sender
from app.tms.client import TMSClient
from app.tms.commands import TMSCommands
from app.tms.errors import TMSError
from app.tms.faults import TMSFaultError

# TMS clean-ERR code -> workflow-facing status string.
_TMS_CODE_STATUS = {
    "NOT_FOUND": "not_found",
    "UNKNOWN_LOAD": "not_found",
    "ALREADY_BOOKED": "already_booked",
    "INVALID_RATE": "invalid_rate",
    "MISSING_FIELD": "invalid_request",
}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    get_logger("adapter").info("adapter_ready", use_stubs=app.state.settings.use_stubs)
    yield


def _build_state(app: FastAPI, s: Settings) -> None:
    """Construct the shared singletons onto app.state. Done at create time (not only in
    lifespan) so the app is fully wired even under a TestClient used without a context."""
    log = get_logger("adapter")
    if not s.adapter_api_key:
        log.warning("adapter_auth_disabled", note="ADAPTER_API_KEY unset; inbound auth is OFF (dev only)")
    app.state.settings = s
    app.state.commands = TMSCommands(TMSClient.from_settings(s))
    app.state.fmcsa = get_fmcsa_client(s)
    app.state.negotiation = NegotiationStore(max_rounds=s.negotiation_max_rounds)
    app.state.otp = OtpStore(ttl_s=s.otp_ttl_s, max_attempts=s.otp_max_attempts, resend_max=s.otp_resend_max)
    app.state.sms = get_sms_sender(s)
    app.state.load_economics = {}  # load_id -> {max_buy, posted_rate}; server-side only
    app.state.audit = []  # offer-event audit trail (Twin persistence is handled by the data layer)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(title="TMS Adapter", version="0.1.0", lifespan=_lifespan)
    _build_state(app, settings)

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        structlog.contextvars.bind_contextvars(request_id=rid)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["x-request-id"] = rid
        return response

    # --- domain exceptions -> HTTP 200 + status (keep the run COMPLETED) --- #
    @app.exception_handler(TMSError)
    async def _on_tms_error(_request: Request, exc: TMSError):
        return JSONResponse(status_code=200, content={"status": _TMS_CODE_STATUS.get(exc.code, "tms_error"), "code": exc.code})

    @app.exception_handler(TMSFaultError)
    async def _on_tms_fault(_request: Request, exc: TMSFaultError):
        return JSONResponse(status_code=200, content={"status": "tms_unavailable", "fault": exc.fault.value})

    @app.exception_handler(CarrierNotFound)
    async def _on_carrier_not_found(_request: Request, _exc: CarrierNotFound):
        return JSONResponse(status_code=200, content={"status": "not_found"})

    @app.exception_handler(FMCSAUpstreamError)
    async def _on_fmcsa_upstream(_request: Request, _exc: FMCSAUpstreamError):
        return JSONResponse(status_code=200, content={"status": "fmcsa_unavailable"})

    @app.exception_handler(CeilingSanityError)
    async def _on_ceiling_sanity(_request: Request, _exc: CeilingSanityError):
        # Unit/inverted-data guard tripped: we cannot safely enforce the ceiling.
        return JSONResponse(status_code=200, content={"status": "ceiling_error"})

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(_request: Request, _exc: RequestValidationError):
        # A missing/empty/wrong-type body field would otherwise be FastAPI's default 422 — a
        # 4xx the workflow's "Ignore 5XX" net does NOT catch, so it can mark the whole run
        # FAILED and lose the call's logged outcome. Hold the same 200 + status invariant as
        # the tool endpoints. The message is deliberately generic: we never echo the offending
        # value, which could carry a secret (e.g. an OTP code) into a response or log.
        # Only the tool endpoints take a request body; the health checks are body-less GETs,
        # so they never reach here and keep their real HTTP codes.
        return JSONResponse(status_code=200, content={"status": "invalid_request", "error": "malformed request"})

    app.include_router(health.router)
    app.include_router(carriers.router)
    app.include_router(loads.router)
    app.include_router(offers.router)
    app.include_router(otp.router)
    app.include_router(bookings.router)
    # Always mount: no real SMS provider is implemented yet, so the outbox stub is always active.
    app.include_router(debug.router)
    return app


app = create_app()
