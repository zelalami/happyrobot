"""Pull config-schemas for every node we'll build, and
resolve the Transfer Popup + AI Extract/Generate event_ids. Dumps to discovery/.
"""
from __future__ import annotations

import json
from pathlib import Path

from hrlib import client_from_env

OUT = Path(__file__).resolve().parent / "discovery"

KNOWN_EVENTS = {
    "web_call_trigger": "6e32e01e-722f-4b8b-9372-500b845686d1",
    "inbound_voice_agent": "0192e5dc-08df-78bf-a549-f43c6bf9f087",
    "webhook_post": "01926f2b-2973-7ebf-ada1-e984251e27ec",
}
INTEGRATIONS_TO_EXPAND = {
    "transfer_popup": "d0e2c0bb-412e-4ff3-8af2-3e7e7725936d",
    "phone_calls": "01929780-8602-73c2-a955-f6015e3b780d",
    "ai": "01926a90-7f9e-785e-891c-51338a7aa70c",
}


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def main():
    hr = client_from_env()
    events = dict(KNOWN_EVENTS)

    # Expand the integrations whose event_ids we still need.
    for label, iid in INTEGRATIONS_TO_EXPAND.items():
        s, detail = hr.get(f"/integrations/{iid}")
        dump(f"integ_detail_{iid}.json", detail)
        evs = (detail or {}).get("events") or []
        print(f"[{label}] {s} — {detail.get('name') if isinstance(detail,dict) else ''}")
        for e in evs:
            if isinstance(e, dict):
                print(f"    {e.get('name')!r:28} id={e.get('id')}")
                nm = (e.get("name") or "").lower()
                if "extract" in nm:
                    events["ai_extract"] = e["id"]
                elif nm == "generate" or "generate" in nm:
                    events["ai_generate"] = e["id"]
                elif "classif" in nm:
                    events["ai_classify"] = e["id"]
                elif "popup" in nm or ("transfer" in nm and "popup" in nm):
                    events["transfer_popup"] = e["id"]
                elif "transfer" in nm:
                    events.setdefault("transfer", e["id"])

    dump("build_events.json", events)
    print("\nResolved build events:", json.dumps(events, indent=2))

    # Pull config-schema for each resolved event.
    print("\n== config-schemas ==")
    schemas = {}
    for label, eid in events.items():
        s, schema = hr.get(f"/events/{eid}/config-schema")
        schemas[label] = {"event_id": eid, "status": s, "schema": schema}
        keys = list(schema.get("properties", {}).keys()) if isinstance(schema, dict) and isinstance(schema.get("properties"), dict) else (list(schema.keys()) if isinstance(schema, dict) else "?")
        print(f"   {label:22} {eid} -> {s}; top props: {keys}")
    dump("build_event_schemas.json", schemas)
    print("\nDone -> discovery/build_events.json, build_event_schemas.json")


if __name__ == "__main__":
    main()
