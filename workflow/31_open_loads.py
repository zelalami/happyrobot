"""Pre-demo helper: list loads that are currently bookable (TMS status OPEN).

Booking writes to the REAL legacy TMS, so a successful demo permanently consumes a
load (it flips OPEN -> pending and can't be re-booked). Run this before a booking demo
to pick a fresh lane to say to the agent:

    python3 31_open_loads.py            # all available loads, dry van first
    python3 31_open_loads.py reefer     # only that equipment

Reads ADAPTER_BASE_URL + ADAPTER_API_KEY from workflow/.env (same as the other helpers).
Hits the adapter's own /loads/search, so it sees exactly what the agent would be pitched.
"""
from __future__ import annotations

import json
import sys
import urllib.request

from hrlib import load_env

# Searching by origin state is the broadest lane filter the adapter exposes; sweeping the
# states the board actually covers gives near-complete coverage (search returns the top few
# per lane). Dedupe by load id across overlapping results.
STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "FL", "GA", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "MD", "MA", "MI", "MN", "MS", "MO", "NE", "NV", "NJ", "NM", "NY", "NC",
    "OH", "OK", "OR", "PA", "SC", "TN", "TX", "UT", "VA", "WA", "WI",
]
STATE_NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "FL": "Florida", "GA": "Georgia", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "NE": "Nebraska",
    "NV": "Nevada", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "SC": "South Carolina", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VA": "Virginia", "WA": "Washington", "WI": "Wisconsin",
}


def main() -> None:
    env = load_env()
    base = env["ADAPTER_BASE_URL"].rstrip("/")
    key = env["ADAPTER_API_KEY"]
    want = sys.argv[1].lower() if len(sys.argv) > 1 else None

    def search(origin_state: str) -> list[dict]:
        req = urllib.request.Request(
            f"{base}/loads/search",
            data=json.dumps({"origin_state": origin_state}).encode(),
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp).get("loads", [])

    by_id: dict[str, dict] = {}
    for st in STATES:
        try:
            for ld in search(st):
                by_id.setdefault(ld["reference_number"], ld)
        except Exception as e:  # one flaky lane shouldn't abort the sweep
            print(f"  ! {st}: {type(e).__name__}", file=sys.stderr)

    # Only OPEN loads are bookable; the adapter maps OPEN -> "available".
    available = [load for load in by_id.values() if load.get("status") == "available"]
    if want:
        available = [load for load in available if want in (load.get("equipment_type") or "").lower()]
    # Dry van first (the scripted demo equipment), then by richest rate.
    available.sort(key=lambda load: ("dry van" not in (load.get("equipment_type") or "").lower(),
                                     -(load.get("posted_carrier_rate") or 0)))

    booked = len(by_id) - sum(1 for load in by_id.values() if load.get("status") == "available")
    print(f"{len(available)} bookable load(s){' · '+want if want else ''}  "
          f"({len(by_id)} seen, {booked} already booked)\n")
    for load in available:
        s = load["stops"]
        o = s[0]["location"]
        d = s[-1]["location"]
        rate = load.get("posted_carrier_rate") or 0
        o_name = STATE_NAME.get(o["state"], o["state"])
        d_name = STATE_NAME.get(d["state"], d["state"])
        print(f"  {load['reference_number']}  {load['equipment_type']:11} posted ${rate}")
        print(f"     SAY: \"{o['city']}, {o_name} to {d['city']}, {d_name}, "
              f"{(load['equipment_type'] or '').lower()}\"")
        print(f"     negotiate: start high (~${int(rate*1.35)}), settle near ${rate}\n")


if __name__ == "__main__":
    main()
