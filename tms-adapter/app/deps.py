"""FastAPI dependencies: inbound bearer auth + accessors for the shared singletons.

The service singletons (TMS commands, FMCSA client, negotiation/OTP stores, SMS
sender, load-economics cache) are built once in the app lifespan and stashed on
`app.state`; these accessors expose them to routers and are the seam tests
override with fakes.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, Request


async def require_bearer(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Enforce `Authorization: Bearer <ADAPTER_API_KEY>` when a key is configured.

    If no key is set, auth is disabled (local dev) — the app logs a warning at boot.
    """
    settings = request.app.state.settings
    key = settings.adapter_api_key.get_secret_value() if settings.adapter_api_key else None
    if key and authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


def get_commands(request: Request):
    return request.app.state.commands


def get_fmcsa(request: Request):
    return request.app.state.fmcsa


def get_negotiation(request: Request):
    return request.app.state.negotiation


def get_otp(request: Request):
    return request.app.state.otp


def get_sms(request: Request):
    return request.app.state.sms


def get_load_economics(request: Request) -> dict:
    return request.app.state.load_economics


def get_audit(request: Request) -> list:
    return request.app.state.audit
