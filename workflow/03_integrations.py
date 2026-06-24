"""Enumerate integrations + their events to find the
event_ids for Webhook, Transfer Popup, End Call, AI Extract/Generate, Condition,
etc. (the node types the existing template workflows don't use, so they weren't
in catalog.json). Dumps to workflow/discovery/.
"""
from __future__ import annotations

import json
from pathlib import Path

from hrlib import client_from_env

OUT = Path(__file__).resolve().parent / "discovery"
OUT.mkdir(exist_ok=True)


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def as_list(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in ("data", "items", "results", "integrations"):
            if isinstance(body.get(k), list):
                return body[k]
    return []


def main():
    hr = client_from_env()

    s, body = hr.get("/integrations/")
    dump("integrations.json", body)
    ints = as_list(body)
    print(f"[integrations] {s} — {len(ints)}")
    for i in ints:
        if isinstance(i, dict):
            print(f"   - {i.get('name')!r} id={i.get('id')} slug={i.get('slug')} "
                  f"events={len(as_list(i.get('events'))) if i.get('events') else '?'}")

    s, cats = hr.get("/integrations/categories")
    dump("integration_categories.json", cats)
    print(f"[categories] {s}")

    # Pull detail (events) for every integration; harvest event catalog.
    events_catalog = {}
    for i in ints:
        if not isinstance(i, dict):
            continue
        iid = i.get("id")
        s, detail = hr.get(f"/integrations/{iid}")
        dump(f"integration_{i.get('slug') or iid}.json", detail)
        evs = as_list(detail.get("events")) if isinstance(detail, dict) else []
        for e in evs:
            if isinstance(e, dict):
                events_catalog[e.get("id")] = {
                    "name": e.get("name"),
                    "slug": e.get("slug"),
                    "integration": i.get("name"),
                    "integration_id": iid,
                }
        if evs:
            names = [e.get("name") for e in evs if isinstance(e, dict)]
            print(f"   events[{i.get('name')}]: {names}")

    dump("events_catalog.json", events_catalog)
    print(f"[events_catalog] {len(events_catalog)} events total")

    # Print the ones we care about for the build.
    WANT = ("webhook", "transfer", "end call", "hang", "extract", "generate",
            "classif", "condition", "twin", "code")
    print("\n== Candidate build nodes ==")
    for eid, meta in events_catalog.items():
        nm = (meta.get("name") or "").lower()
        if any(w in nm for w in WANT):
            print(f"   {meta.get('name')!r:32} event_id={eid}  ({meta.get('integration')})")


if __name__ == "__main__":
    main()
