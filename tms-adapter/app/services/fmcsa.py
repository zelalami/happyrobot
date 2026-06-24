"""FMCSA carrier-authority lookup — two live backends + a deterministic stub.

The gate the workflow checks before OTP is `allowed_to_operate` (and `status ==
"active"`). We also resolve the carrier's FMCSA-registered phone here so the OTP
SMS goes to a SERVER-resolved number, never a caller-supplied one. The raw phone
stays server-side; only a masked form is exposed to the workflow.

Two live backends, selected by `FMCSA_SOURCE` (default `soda`):

* ``soda`` — FMCSA's official open data on the federal portal
  (``data.transportation.gov``, SODA/Socrata REST). No key required. This is the
  default because the QCMobile host below returns an HTML 403 to our server-to-server
  calls (reproduced from three independent networks; the webKey itself is valid and
  works from a real browser). The exact trigger, whether client fingerprint, IP/region,
  or both, was not isolated. SODA is a different host and is reachable from the deployment.
* ``qcmobile`` — the keyed QCMobile / Web Services API (``mobile.fmcsa.dot.gov``);
  driven by the challenge-issued `FMCSA_API_KEY`. Kept selectable for completeness
  (the challenge email nudges toward it), even though it is WAF-blocked
  programmatically today.

Mappers are pure functions (`map_carrier` / `map_soda_carrier`, `extract_carrier`
/ `extract_soda_carrier`) so they are unit-tested without network; `USE_STUBS`
(the default) keeps tests and the reproducible demo independent of either upstream.

QCMobile shape (documented, stable):
  GET /qc/services/carriers/docket-number/{mc}?webKey=KEY -> {"content": [{"carrier": {...}}], ...}
  GET /qc/services/carriers/{dot}?webKey=KEY              -> {"content": {"carrier": {...}}, ...}
  carrier fields: allowedToOperate("Y"/"N"), statusCode("A"/"I"), legalName, dbaName,
                  dotNumber, telephone, phyState, ...

SODA census shape (dataset ``az4n-8mr2``): a flat JSON array of carrier rows.
Authority lives PER DOCKET: ``docketN`` + ``docketNprefix`` (MC/MX/FF) +
``docketN_status_code`` ("A" = active). An MC number can sit in any of docket1..3,
and the SAME digits can exist under different prefixes for DIFFERENT carriers
(e.g. MC 44110 is a motor carrier, FF 44110 is a freight forwarder) — so we match
on ``prefix == 'MC' AND number`` across all three slots, never number alone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.services.phone import mask_phone, normalize_phone

FMCSA_BASE_URL = "https://mobile.fmcsa.dot.gov/qc/services"
# FMCSA open-data census (Socrata/SODA) — reachable server-to-server, no key needed.
SODA_BASE_URL = "https://data.transportation.gov/resource/az4n-8mr2.json"
_DOCKET_SLOTS = ("1", "2", "3")


def _digits(value: str | int | None) -> str:
    """Reduce an identifier to ASCII digits only.

    MC/DOT numbers are numeric, so stripping to ASCII digits both normalizes
    spoken input ("MC 44110") AND makes SoQL injection impossible — only the
    bytes U+0030..U+0039 ever reach the SODA ``$where`` clause (note ``\\d`` is
    Unicode-aware and would let fullwidth/Arabic-Indic digits through, so we use
    an explicit ASCII class). Empty result => no usable identifier.
    """
    return re.sub(r"[^0-9]", "", str(value)) if value is not None else ""


class CarrierNotFound(Exception):
    """No carrier matched the MC/DOT (maps to HTTP 404)."""


class FMCSAUpstreamError(Exception):
    """FMCSA was unreachable or returned an unusable response (maps to 502)."""


@dataclass
class Carrier:
    status: str                       # "active" | "not_authorized"
    allowed_to_operate: bool
    mc_number: str | None = None
    dot_number: str | None = None
    legal_name: str | None = None
    dba_name: str | None = None
    # SERVER-SIDE only (the OTP destination); never echoed raw. repr=False keeps the
    # raw number out of any accidental log/traceback repr — to_bridge masks it.
    registered_phone: str | None = field(default=None, repr=False)
    raw_status_code: str | None = None

    def to_bridge(self) -> dict:
        """bridge-api `carrier` shape. registered_phone is exposed MASKED only."""
        ident = self.mc_number or self.dot_number or "UNKNOWN"
        return {
            "carrier_id": f"CAR-{ident}",
            "carrier_name": self.legal_name or self.dba_name,
            "status": self.status,
            "dot_number": self.dot_number,
            "mc_number": self.mc_number,
            "authority": {"allowed_to_operate": self.allowed_to_operate},
            "registered_phone_masked": mask_phone(self.registered_phone),
            "dba_name": self.dba_name,
        }


def map_carrier(raw: dict[str, Any], *, mc: str | None = None, dot: str | None = None) -> Carrier:
    """Map one raw QCMobile carrier object to our normalized Carrier."""
    allowed = str(raw.get("allowedToOperate", "")).strip().upper() == "Y"
    dot_number = raw.get("dotNumber")
    return Carrier(
        status="active" if allowed else "not_authorized",
        allowed_to_operate=allowed,
        mc_number=mc,
        dot_number=str(dot_number) if dot_number is not None else (dot or None),
        legal_name=(raw.get("legalName") or None),
        dba_name=(raw.get("dbaName") or None),
        registered_phone=normalize_phone(raw.get("telephone")),
        raw_status_code=raw.get("statusCode"),
    )


def extract_carrier(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull the single carrier object out of a QCMobile response envelope.

    `content` may be a list (docket-number lookups) or an object (DOT lookups).
    """
    content = payload.get("content")
    if not content:
        raise CarrierNotFound("no content")
    if isinstance(content, list):
        item = content[0]
        carrier = item.get("carrier", item) if isinstance(item, dict) else None
    elif isinstance(content, dict):
        carrier = content.get("carrier", content)
    else:
        carrier = None
    if not carrier:
        raise CarrierNotFound("no carrier in content")
    return carrier


class FMCSAClient(Protocol):
    async def lookup(self, *, mc: str | None = None, dot: str | None = None) -> Carrier: ...


class LiveFMCSAClient:
    def __init__(self, api_key: str, *, base_url: str = FMCSA_BASE_URL, timeout: float = 10.0):
        self._key = api_key
        self._base_url = base_url
        self._timeout = timeout

    async def lookup(self, *, mc: str | None = None, dot: str | None = None) -> Carrier:
        if mc is None and dot is None:
            raise ValueError("mc or dot required")
        mc_digits, dot_digits = _digits(mc), _digits(dot)  # same sanitizer as the SODA path
        if not (mc_digits or dot_digits):
            raise CarrierNotFound(str(mc or dot))          # no ASCII digits -> fail closed
        path = f"/carriers/docket-number/{mc_digits}" if mc_digits else f"/carriers/{dot_digits}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base_url}{path}", params={"webKey": self._key})
        except httpx.HTTPError as e:
            raise FMCSAUpstreamError(f"request failed: {type(e).__name__}") from e
        if resp.status_code == 404:
            raise CarrierNotFound(f"{mc_digits or dot_digits}")
        if resp.status_code >= 400:
            raise FMCSAUpstreamError(f"HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as e:
            raise FMCSAUpstreamError("non-JSON response") from e
        return map_carrier(extract_carrier(payload), mc=mc_digits or None, dot=dot_digits or None)


class StubFMCSAClient:
    """Deterministic FMCSA for tests + reproducible demo (the default via USE_STUBS).

    Sentinels for QA edge tests: MC "000000" -> not found; MC "999999" -> not authorized;
    anything else -> an active carrier with a deterministic name + registered phone.
    """

    async def lookup(self, *, mc: str | None = None, dot: str | None = None) -> Carrier:
        ident = (mc or dot or "").strip()
        if not ident:
            raise ValueError("mc or dot required")
        if ident in ("000000", "0"):
            raise CarrierNotFound(ident)
        allowed = ident != "999999"
        phone = "+1555" + ident.zfill(7)[-7:]
        return Carrier(
            status="active" if allowed else "not_authorized",
            allowed_to_operate=allowed,
            mc_number=mc,
            dot_number=dot,
            legal_name=f"CARRIER {ident} LLC",
            dba_name=None,
            registered_phone=phone,
            raw_status_code="A" if allowed else "I",
        )


def map_soda_carrier(row: dict[str, Any], *, mc: str | None = None, dot: str | None = None) -> Carrier:
    """Map one SODA census row to our normalized Carrier.

    Authority comes ONLY from an MC-prefixed docket — never from an FF/MX/broker
    docket or the bare census ``status_code``. For an MC lookup we use the slot
    whose ``prefix == 'MC'`` AND number == the queried MC; for a DOT lookup we use
    the carrier's MC docket (the first MC-prefixed slot). If no qualifying MC docket
    exists, the carrier is not_authorized (a freight forwarder / broker is not
    authorized to haul). ``allowed_to_operate`` == that docket's status is "A".
    """
    mc_digits = _digits(mc)
    status_code = ""        # default: no active MC authority found on this row
    matched_mc: str | None = None
    for i in _DOCKET_SLOTS:
        num = (row.get(f"docket{i}") or "").strip()
        pref = (row.get(f"docket{i}prefix") or "").strip().upper()
        if pref != "MC":
            continue
        # MC lookup must match the queried number; DOT lookup takes the carrier's
        # MC docket (any). Either way authority is read ONLY off an MC docket.
        if mc_digits and num != mc_digits:
            continue
        status_code = (row.get(f"docket{i}_status_code") or "").strip().upper()
        matched_mc = num or None
        break
    allowed = status_code == "A"
    dot_number = row.get("dot_number")
    return Carrier(
        status="active" if allowed else "not_authorized",
        allowed_to_operate=allowed,
        mc_number=mc_digits or matched_mc or None,
        dot_number=str(dot_number) if dot_number is not None else (_digits(dot) or None),
        legal_name=(row.get("legal_name") or None),
        dba_name=(row.get("dba_name") or None),
        registered_phone=normalize_phone(row.get("phone")),
        raw_status_code=status_code or None,
    )


def extract_soda_carrier(payload: Any) -> dict[str, Any]:
    """Pull the single carrier row out of a SODA response (a JSON array)."""
    if not isinstance(payload, list) or not payload:
        raise CarrierNotFound("no rows")
    row = payload[0]
    if not isinstance(row, dict):
        raise CarrierNotFound("unexpected row shape")
    return row


class SodaFMCSAClient:
    """FMCSA authority via the federal open-data SODA API (default live backend).

    No webKey required; an optional Socrata app token (``X-App-Token``) raises rate
    limits. Reachable server-to-server, unlike QCMobile's WAF-blocked host.
    """

    def __init__(self, *, base_url: str = SODA_BASE_URL, app_token: str | None = None,
                 timeout: float = 10.0, transport: httpx.AsyncBaseTransport | None = None):
        self._base_url = base_url
        self._app_token = app_token
        self._timeout = timeout
        self._transport = transport

    async def lookup(self, *, mc: str | None = None, dot: str | None = None) -> Carrier:
        if mc is None and dot is None:
            raise ValueError("mc or dot required")
        mc_digits, dot_digits = _digits(mc), _digits(dot)
        if not (mc_digits or dot_digits):
            # an identifier was supplied but carried no ASCII digits -> fail closed
            raise CarrierNotFound(str(mc or dot))
        params: dict[str, str] = {"$limit": "1"}
        if mc_digits:
            # prefix=='MC' AND number, across all docket slots: number-only is
            # ambiguous (same digits can be an MC for one carrier, an FF for another).
            params["$where"] = " OR ".join(
                f"(docket{i}prefix='MC' AND docket{i}='{mc_digits}')" for i in _DOCKET_SLOTS
            )
        else:
            params["dot_number"] = dot_digits
        headers = {"X-App-Token": self._app_token} if self._app_token else {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(self._base_url, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise FMCSAUpstreamError(f"request failed: {type(e).__name__}") from e
        if resp.status_code >= 400:
            raise FMCSAUpstreamError(f"HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as e:
            raise FMCSAUpstreamError("non-JSON response") from e
        return map_soda_carrier(extract_soda_carrier(payload), mc=mc_digits or None, dot=dot_digits or None)


def get_fmcsa_client(settings) -> FMCSAClient:
    """Pick the FMCSA backend.

    ``USE_STUBS`` always wins => deterministic stub. Otherwise ``FMCSA_SOURCE``
    selects the live backend: ``soda`` (default, no key, works S2S) · ``qcmobile``
    (needs webKey; degrades to stub if absent) · ``stub``.
    """
    if settings.use_stubs:
        return StubFMCSAClient()
    source = getattr(settings, "fmcsa_source", "soda")
    if source == "stub":
        return StubFMCSAClient()
    if source == "qcmobile":
        if not settings.fmcsa_api_key:
            return StubFMCSAClient()  # QCMobile needs a webKey; fail safe to stub
        return LiveFMCSAClient(settings.fmcsa_api_key.get_secret_value())
    token = getattr(settings, "fmcsa_soda_app_token", None)
    return SodaFMCSAClient(app_token=token.get_secret_value() if token else None)
