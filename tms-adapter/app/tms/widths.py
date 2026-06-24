"""Confirmed fixed-width column table + per-field normalisation.

Widths were MEASURED from the TMS sweep captures — all five sampled LOAD_GET
records agreed (see tests/fixtures/transcripts/SWEEP_SUMMARY.md). The wire is
SPACE-padded, never zero-padded, so:
  * numerics  -> rstrip(' ') then int()   ("1704    " -> 1704, "0001950" -> 1950)
  * text      -> rstrip(' ')              (fully-blank field -> None)
  * dates     -> YYYYMMDDHHMMSS -> ISO-8601
  * tokens    -> rstrip(' ')              (id/state/zip/status kept as strings)

`width=None` means "known field, width not yet captured on the wire" (e.g. the
LOAD_BOOK echo fields). We still normalise it but do NOT width-validate, so an
uncaptured-but-valid field never trips a false MALFORMED. Unknown keys are kept
verbatim (trimmed) and never width-checked, so a new TMS column won't crash us.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any

from app.tms.faults import TMSFault, TMSFaultError


class Kind(Enum):
    TEXT = auto()     # rstrip(' '); fully blank -> None
    NUMERIC = auto()  # rstrip(' ') -> int; blank -> None
    DATE = auto()     # YYYYMMDDHHMMSS -> ISO-8601; blank -> None
    TOKEN = auto()    # short fixed code (id/state/zip/status); rstrip, keep str


@dataclass(frozen=True)
class FieldSpec:
    width: int | None
    kind: Kind


# Confirmed from the sweep (LOAD_GET full record + LOAD_QUERY subset).
FIELD_SPECS: dict[str, FieldSpec] = {
    "LOAD_ID":     FieldSpec(12, Kind.TOKEN),
    "ORIG_CITY":   FieldSpec(30, Kind.TEXT),
    "ORIG_STATE":  FieldSpec(2, Kind.TOKEN),
    "ORIG_ZIP":    FieldSpec(5, Kind.TOKEN),
    "DEST_CITY":   FieldSpec(30, Kind.TEXT),
    "DEST_STATE":  FieldSpec(2, Kind.TOKEN),
    "DEST_ZIP":    FieldSpec(5, Kind.TOKEN),
    "PICKUP_DT":   FieldSpec(14, Kind.DATE),
    "DELIVERY_DT": FieldSpec(14, Kind.DATE),
    "EQTYPE":      FieldSpec(10, Kind.TEXT),
    "RATE":        FieldSpec(8, Kind.NUMERIC),
    "WEIGHT":      FieldSpec(8, Kind.NUMERIC),
    "COMMODITY":   FieldSpec(30, Kind.TEXT),
    "PIECES":      FieldSpec(6, Kind.NUMERIC),
    "MILES":       FieldSpec(6, Kind.NUMERIC),
    "DIMS":        FieldSpec(30, Kind.TEXT),
    "NOTES":       FieldSpec(120, Kind.TEXT),
    "STATUS":      FieldSpec(8, Kind.TOKEN),
    "MAX_BUY":     FieldSpec(8, Kind.NUMERIC),
    # Known but not yet captured on the wire (LOAD_BOOK response) -> no width check.
    "BOOKING_REF": FieldSpec(None, Kind.TOKEN),
    "TIMESTAMP":   FieldSpec(None, Kind.DATE),
    "MC_NUM":      FieldSpec(None, Kind.TOKEN),
    "AGREED_RATE": FieldSpec(None, Kind.NUMERIC),
}


def _text(raw: str) -> str | None:
    v = raw.rstrip(" ")
    return v or None


def _numeric(key: str, raw: str) -> int | None:
    v = raw.rstrip(" ")
    if v == "":
        return None
    try:
        return int(v)
    except ValueError as e:
        raise TMSFaultError(TMSFault.MALFORMED, f"{key}: non-numeric {raw!r}") from e


def _date(key: str, raw: str) -> str | None:
    v = raw.rstrip(" ")
    if v == "":
        return None
    try:
        return datetime.strptime(v, "%Y%m%d%H%M%S").isoformat()
    except ValueError as e:
        raise TMSFaultError(TMSFault.MALFORMED, f"{key}: bad timestamp {raw!r}") from e


def normalize_field(key: str, raw: str) -> Any:
    """Validate width then trim/type a single on-wire value."""
    spec = FIELD_SPECS.get(key)
    if spec is None:
        # Unknown column: keep it, trim the pad, blank -> None. No width check.
        return _text(raw)
    if spec.width is not None and len(raw) > spec.width:
        raise TMSFaultError(
            TMSFault.MALFORMED, f"{key}: on-wire width {len(raw)} exceeds {spec.width}"
        )
    if spec.kind is Kind.NUMERIC:
        return _numeric(key, raw)
    if spec.kind is Kind.DATE:
        return _date(key, raw)
    # TEXT and TOKEN both rstrip; blank -> None.
    return _text(raw)


def normalize_record(raw: dict[str, str]) -> dict[str, Any]:
    return {k: normalize_field(k, v) for k, v in raw.items()}
