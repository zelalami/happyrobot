"""Find event_ids for the core build nodes
(Webhook, Transfer Popup, AI Extract/Generate, End call) via search + full
pagination + the known voice/trigger integration ids. Dumps to discovery/.
"""
from __future__ import annotations

import json
from pathlib import Path

from hrlib import client_from_env

OUT = Path(__file__).resolve().parent / "discovery"
KNOWN = {
    "voice": "0192e48a-81d8-71cb-93dc-efd8ad63d86b",       # Web call + Voice Agents
    "number_trigger": "01926a93-064a-7a00-81b2-8ab78d5907e0",
}


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def as_list(body, *keys):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in ("data", "items", "results", "integrations", "events", *keys):
            if isinstance(body.get(k), list):
                return body[k]
    return []


def harvest(detail, integ_name, catalog):
    for e in as_list(detail, "events"):
        if isinstance(e, dict) and e.get("id"):
            catalog[e["id"]] = {"name": e.get("name"), "slug": e.get("slug"),
                                "integration": integ_name}


def main():
    hr = client_from_env()
    catalog = {}

    # 1) Full paginated integration list
    page = 1
    all_ints = []
    while True:
        s, body = hr.get(f"/integrations/?page={page}&page_size=200")
        items = as_list(body)
        all_ints.extend(items)
        if len(items) < 200 or page > 20:
            break
        page += 1
    dump("integrations_all.json", all_ints)
    print(f"[integrations all] {len(all_ints)} total")

    # 2) Search for the node types we need
    for term in ("webhook", "transfer", "extract", "generate", "http", "code", "twin"):
        s, body = hr.get(f"/integrations/?search={term}")
        for i in as_list(body):
            if isinstance(i, dict):
                print(f"   search[{term}] -> {i.get('name')!r} id={i.get('id')}")

    # 3) Fetch full detail (events) for known + all integrations whose name hints core
    targets = set(KNOWN.values())
    for i in all_ints:
        if isinstance(i, dict):
            nm = (i.get("name") or "").lower()
            if any(w in nm for w in ("voice", "webhook", "core", "happyrobot",
                                     "default", "transfer", "ai ", "tool", "http",
                                     "logic", "data")):
                targets.add(i.get("id"))
    for iid in targets:
        s, detail = hr.get(f"/integrations/{iid}")
        if isinstance(detail, dict):
            nm = detail.get("name")
            dump(f"integ_detail_{iid}.json", detail)
            harvest(detail, nm, catalog)
            evs = [e.get("name") for e in as_list(detail, "events") if isinstance(e, dict)]
            print(f"   detail[{nm}] id={iid} events={evs}")

    dump("events_catalog_full.json", catalog)

    print("\n== Build-node candidates ==")
    WANT = ("webhook", "transfer", "extract", "generate", "hangup", "end call",
            "http", "api call", "condition", "twin", "code", "ai ")
    for eid, meta in catalog.items():
        nm = (meta.get("name") or "").lower()
        if any(w in nm for w in WANT):
            print(f"   {meta.get('name')!r:28} event_id={eid}  ({meta.get('integration')})")


if __name__ == "__main__":
    main()
