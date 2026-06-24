"""Adapter configuration.

Loaded from the gitignored `tms-adapter/.env` locally and from the platform's
secret store in the cloud. Secrets have NO defaults, so a missing TMS credential
fails the process at boot rather than silently degrading. Field names mirror the
real `.env` (e.g. `TMS_TOKEN`, `FMCSA_API_KEY`, `TWILIO_*`, `USE_STUBS`).

Secrets are held as `SecretStr` so they never appear in logs/reprs/tracebacks;
call `.get_secret_value()` at the single point of use (frame encode, API call).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ADAPTER_ROOT = Path(__file__).resolve().parent.parent  # tms-adapter/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ADAPTER_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Legacy TMS (required; bearer secret) ---
    tms_host: str
    tms_port: int
    tms_token: SecretStr

    # --- FMCSA (carrier authority; live only when not stubbed) ---
    # FMCSA_SOURCE picks the live backend:
    #   soda     => federal open data (data.transportation.gov); no key; works S2S; DEFAULT.
    #   qcmobile => keyed QCMobile API (mobile.fmcsa.dot.gov); uses FMCSA_API_KEY; WAF-blocked S2S.
    #   stub     => deterministic stub even when USE_STUBS is false.
    fmcsa_source: str = "soda"
    fmcsa_api_key: SecretStr | None = None              # QCMobile webKey (qcmobile source only)
    fmcsa_soda_app_token: SecretStr | None = None       # optional Socrata token (raises rate limits)

    # --- SMS: Twilio trial (OTP delivery; required only when not stubbed) ---
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None

    # --- Adapter inbound bearer (optional locally; SET IN DEPLOY) ---
    # When unset, inbound auth is disabled (fine for local dev). The Webhook
    # node sends this as `Authorization: Bearer <adapter_api_key>`.
    adapter_api_key: SecretStr | None = None

    # --- Behaviour ---
    # true => FMCSA/SMS use deterministic stubs; no real texts sent. Default on
    # so tests and a fresh clone never depend on external accounts or hit the live
    # TMS/FMCSA unprompted; the cloud deploy sets USE_STUBS=false explicitly.
    use_stubs: bool = True

    # --- TMS transport tunables (seconds) ---
    tms_deadline_s: float = 8.0          # hard wall-clock budget per request
    tms_connect_timeout_s: float = 3.0
    tms_read_timeout_s: float = 6.0

    # --- OTP / negotiation policy ---
    otp_ttl_s: int = 300
    otp_max_attempts: int = 3
    otp_resend_max: int = 3
    negotiation_max_rounds: int = 3

    log_level: str = "INFO"

    @field_validator("fmcsa_source")
    @classmethod
    def _check_fmcsa_source(cls, v: str) -> str:
        v = (v or "soda").strip().lower()
        if v not in {"soda", "qcmobile", "stub"}:
            raise ValueError("fmcsa_source must be one of: soda, qcmobile, stub")
        return v


@lru_cache
def get_settings() -> Settings:
    """Process-wide singleton (cached) for use as a FastAPI dependency."""
    return Settings()
