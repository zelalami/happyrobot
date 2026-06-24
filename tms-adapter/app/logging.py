"""structlog config with secret redaction.

Every log line is JSON. A redaction processor scrubs the configured secrets (TMS
token, adapter key, FMCSA key, Twilio token) and any `AUTH:<token>` substring
from a raw frame before it is emitted — defence-in-depth so a stray log of a wire
frame can never leak the bearer token. OTP codes are never logged anywhere
by design.
"""
from __future__ import annotations

import logging
import re
import sys

import structlog

_AUTH_RE = re.compile(r"(AUTH:)[^|\s]+")
# Don't treat a trivially-short value as a secret to scrub everywhere — a 1-char
# token would redact every occurrence of that char and shred the logs. Real
# bearer/API secrets are far longer than this floor.
_MIN_SECRET_LEN = 6


def make_redactor(secrets: list[str]):
    """Build a structlog processor that scrubs known (sufficiently long) secrets and
    any `AUTH:<token>` substring from every event-dict value."""
    real = [s for s in secrets if s and len(s) >= _MIN_SECRET_LEN]

    def _scrub(value):
        if isinstance(value, str):
            for sec in real:
                if sec in value:
                    value = value.replace(sec, "***REDACTED***")
            value = _AUTH_RE.sub(r"\1***REDACTED***", value)
        return value

    def processor(_logger, _method, event_dict):
        return {k: _scrub(v) for k, v in event_dict.items()}

    return processor


def configure_logging(settings) -> None:
    secrets: list[str] = []
    for val in (settings.tms_token, settings.adapter_api_key, settings.fmcsa_api_key,
                settings.fmcsa_soda_app_token, settings.twilio_auth_token):
        if val is not None:
            secrets.append(val.get_secret_value())
    redact_processor = make_redactor(secrets)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(*args, **kwargs):
    return structlog.get_logger(*args, **kwargs)
