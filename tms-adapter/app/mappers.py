"""Map normalized TMS records (from framing.decode_response) to bridge-api JSON.

CRITICAL: `MAX_BUY` is NEVER serialized into a load response surfaced to the
workflow/LLM. `map_load_detail` instead emits a boolean `ceiling_available`; the
raw ceiling is read server-side only (seeded into the load-economics cache for
`/offers/evaluate`).
"""
from __future__ import annotations

from typing import Any

EQUIPMENT_TMS_TO_BRIDGE = {
    "DRY_VAN": "Dry Van",
    "REEFER": "Reefer",
    "FLATBED": "Flatbed",
    "STEP_DECK": "Step Deck",
    "POWER_ONLY": "Power Only",
}
EQUIPMENT_BRIDGE_TO_TMS = {v.lower(): k for k, v in EQUIPMENT_TMS_TO_BRIDGE.items()}


def bridge_equipment_to_tms(value: str | None) -> str | None:
    """'Dry Van' -> 'DRY_VAN'. Accepts a TMS id passed through verbatim too."""
    if not value:
        return None
    v = value.strip()
    return EQUIPMENT_BRIDGE_TO_TMS.get(v.lower(), v.upper().replace(" ", "_"))


def tms_equipment_to_bridge(value: str | None) -> str | None:
    if not value:
        return None
    return EQUIPMENT_TMS_TO_BRIDGE.get(value, value)


def _bridge_status(status: str | None) -> str | None:
    if not status:
        return None
    return "available" if status.upper() == "OPEN" else status.lower()


def _stop(kind: str, city, state, zip_, when) -> dict[str, Any]:
    return {
        "type": kind,
        "location": {"city": city, "state": state, "zip": zip_, "country": "US"},
        "stop_timestamp_open": when,
    }


def map_load_summary(rec: dict[str, Any]) -> dict[str, Any]:
    """LOAD_QUERY record -> bridge `loads[]` entry (no max_buy, subset of fields)."""
    return {
        "reference_number": rec.get("LOAD_ID"),
        "equipment_type": tms_equipment_to_bridge(rec.get("EQTYPE")),
        "status": _bridge_status(rec.get("STATUS")),
        "posted_carrier_rate": rec.get("RATE"),
        "miles": rec.get("MILES"),
        "stops": [
            _stop("origin", rec.get("ORIG_CITY"), rec.get("ORIG_STATE"), rec.get("ORIG_ZIP"), rec.get("PICKUP_DT")),
            _stop("destination", rec.get("DEST_CITY"), rec.get("DEST_STATE"), rec.get("DEST_ZIP"), rec.get("DELIVERY_DT")),
        ],
    }


def map_load_detail(rec: dict[str, Any]) -> dict[str, Any]:
    """LOAD_GET record -> bridge `load`. max_buy STRIPPED; ceiling_available bool only."""
    out = map_load_summary(rec)
    out.update({
        "weight": rec.get("WEIGHT"),
        "commodity_type": rec.get("COMMODITY"),
        "number_of_pieces": rec.get("PIECES"),
        "dimensions": rec.get("DIMS"),
        "sale_notes": rec.get("NOTES"),
        "ceiling_available": rec.get("MAX_BUY") is not None,
    })
    return out
