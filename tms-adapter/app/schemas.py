"""Pydantic request models for the adapter's POST+JSON tool endpoints.

All tool calls are POST with a JSON body so run_id + params travel cleanly and we
never query-encode city/equipment strings.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, StringConstraints

# A required string that must carry real content. Surrounding whitespace is stripped and an
# empty/blank value is rejected during request validation, so malformed input (e.g. an empty
# `mc`) is turned away by the RequestValidationError handler as HTTP 200 + invalid_request
# rather than reaching a service that would raise an uncaught 500.
NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FindCarrierRequest(BaseModel):
    mc: str | None = None
    dot: str | None = None


class SearchLoadsRequest(BaseModel):
    origin_state: str | None = None
    origin_city: str | None = None
    destination_state: str | None = None
    destination_city: str | None = None
    equipment_type: str | None = None
    pickup_date: str | None = None
    max_results: int | None = None


class GetLoadRequest(BaseModel):
    load_id: NonBlankStr


class EvaluateOfferRequest(BaseModel):
    run_id: NonBlankStr
    load_id: NonBlankStr
    carrier_offer: int


class LogOfferRequest(BaseModel):
    run_id: NonBlankStr
    load_id: NonBlankStr
    carrier_offer: int
    mc_number: str | None = None
    notes: str | None = None


class OtpSendRequest(BaseModel):
    run_id: NonBlankStr
    mc: NonBlankStr  # the run's FMCSA-established MC; the destination is resolved server-side


class OtpVerifyRequest(BaseModel):
    run_id: NonBlankStr
    mc: NonBlankStr
    code: NonBlankStr


class BookingRequest(BaseModel):
    run_id: NonBlankStr
    load_id: NonBlankStr
    mc_number: NonBlankStr
    agreed_rate: int
