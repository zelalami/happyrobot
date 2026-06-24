"""Harvest the real Twin node + post-call write contract.

Read-only. Resolves (no guessing) the things the workflow catalog never captured
because no existing org workflow used Twin:
  1. The "Write to Twin" / "Read from Twin" node event_ids + config-schemas
     (via /integrations/?category=Data&include_events=true&include_config_schema=true).
  2. The AI-Extract event config-schema (event id already known from the workflow build).
  3. The current inbound-carrier-sales graph + the voice-agent node's outputs
     (to find the transcript variable + the post-call attach point for the write chain).

Dumps to twin/discovery/*.json and prints summaries only (no secrets).
"""
from __future__ import annotations

import json

from _common import as_list, client_from_env, dump

# resolved ids (workflow/buildlib.py)
VERSION_ID = "019eeef8-89ac-70ac-b906-d1f8101e9f8a"
VOICE_AGENT_NODE_ID = "019eef02-321b-716f-a757-243a9bb7d56d"
AI_EXTRACT_EVENT = "01926f30-36a3-7394-8f73-eeead5d7f948"


def main() -> None:
    hr = client_from_env()

    # 1) Twin / Data integrations WITH events + config schema -----------------
    found_events: dict[str, dict] = {}
    for q in ("category=Data", "search=twin", "search=database"):
        path = f"/integrations/?{q}&include_events=true&include_config_schema=true&page_size=100"
        s, body = hr.get(path)
        ints = as_list(body)
        print(f"\n[{q}] {s} — {len(ints)} integrations")
        for i in ints:
            if not isinstance(i, dict):
                continue
            nm = i.get("name")
            evs = as_list(i, "events")
            print(f"   integration {nm!r} id={i.get('id')} slug={i.get('slug')} events={len(evs)}")
            for e in evs:
                if isinstance(e, dict) and e.get("id"):
                    found_events[e["id"]] = {
                        "name": e.get("name"), "slug": e.get("slug"),
                        "integration": nm, "config_schema": e.get("config_schema"),
                    }
                    print(f"        - event {e.get('name')!r}  id={e.get('id')}  slug={e.get('slug')}")
    dump("twin_events.json", found_events)

    # Flag the write/read-to-twin candidates explicitly
    print("\n== Twin node candidates ==")
    for eid, meta in found_events.items():
        nm = (meta.get("name") or "").lower()
        if "twin" in nm or "twin" in (meta.get("slug") or "").lower():
            print(f"   {meta.get('name')!r:24} event_id={eid}")

    # 2) AI-Extract config-schema (id known) ----------------------------------
    s, schema = hr.get(f"/events/{AI_EXTRACT_EVENT}/config-schema")
    dump("ai_extract_schema.json", schema)
    title = schema.get("title") if isinstance(schema, dict) else ""
    print(f"\n[ai_extract config-schema] {s} {title!r}")
    if isinstance(schema, dict):
        props = (schema.get("properties") or schema.get("schema", {}).get("properties") or {})
        print("   top-level config keys:", list(props.keys())[:30])

    # 3) Current graph + the voice-agent node (transcript var + attach point) --
    s, nodes_body = hr.get(f"/versions/{VERSION_ID}/nodes")
    dump("current_nodes.json", nodes_body)
    nodes = as_list(nodes_body)
    print(f"\n[current graph] {s} — {len(nodes)} nodes")
    for n in nodes:
        if not isinstance(n, dict):
            continue
        marker = "  <-- VOICE AGENT" if n.get("id") == VOICE_AGENT_NODE_ID else ""
        print(f"   {n.get('type'):8} {n.get('name')!r:34} id={n.get('id')} parent={n.get('parent_id')}{marker}")

    # Inspect the voice-agent node's output variables if the API exposes them
    s, va = hr.get(f"/versions/{VERSION_ID}/nodes/{VOICE_AGENT_NODE_ID}")
    dump("voice_agent_node.json", va)
    print(f"\n[voice-agent node detail] {s} — keys: "
          f"{list(va.get('data', va).keys()) if isinstance(va, dict) else type(va)}")

    print("\nDone. See twin/discovery/*.json")


if __name__ == "__main__":
    main()
