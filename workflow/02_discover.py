"""Harvest the live platform contract.

Read-only. Dumps to workflow/discovery/*.json:
  - workflows.json        : all existing workflows (id, name, slug, latest version)
  - templates.json        : GET /workflows/templates raw
  - wf_<slug>_nodes.json  : node graph of each existing workflow's latest version
  - catalog.json          : distinct (type, event_id, name) harvested across all graphs
  - event_<id>.json       : config-schema for each distinct event_id

This gives the real event_ids + configuration shapes we build from (no guessing).
Prints summaries only — no secrets.
"""
from __future__ import annotations

import json
from pathlib import Path

from hrlib import client_from_env, load_env

OUT = Path(__file__).resolve().parent / "discovery"
OUT.mkdir(exist_ok=True)


def dump(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def as_list(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in ("data", "items", "results", "workflows"):
            if isinstance(body.get(k), list):
                return body[k]
    return []


def main() -> None:
    env = load_env()
    hr = client_from_env(env)

    # 1) Workflows
    status, body = hr.get("/workflows/")
    dump("workflows.json", body)
    wfs = as_list(body)
    print(f"[workflows] {status} — {len(wfs)} found")
    for w in wfs:
        if isinstance(w, dict):
            lv = w.get("latest_version") or {}
            print(f"   - {w.get('name')!r}  slug={w.get('slug')}  id={w.get('id')}  "
                  f"ver={lv.get('id')}  published={lv.get('is_published')}")

    # 2) Templates
    status, body = hr.get("/workflows/templates")
    dump("templates.json", body)
    print(f"[templates] {status} — keys/sample written to discovery/templates.json")

    # 3) Each workflow's node graph (+ collect event catalog)
    catalog: dict[str, dict] = {}
    for w in wfs:
        if not isinstance(w, dict):
            continue
        wid = w.get("id")
        slug = w.get("slug") or wid
        lv = w.get("latest_version") or {}
        vid = lv.get("id")
        if not vid:
            # fetch detail to resolve latest version
            s, detail = hr.get(f"/workflows/{wid}")
            vid = ((detail or {}).get("latest_version") or {}).get("id") if isinstance(detail, dict) else None
        if not vid:
            print(f"   ! {slug}: no version id; skipping nodes")
            continue
        s, nodes_body = hr.get(f"/versions/{vid}/nodes")
        dump(f"wf_{slug}_nodes.json", nodes_body)
        nodes = as_list(nodes_body)
        kinds: dict[str, int] = {}
        for n in nodes:
            if not isinstance(n, dict):
                continue
            t = n.get("type")
            eid = n.get("event_id")
            kinds[t] = kinds.get(t, 0) + 1
            if eid:
                key = f"{t}:{eid}"
                catalog.setdefault(key, {
                    "type": t, "event_id": eid,
                    "example_name": n.get("name"),
                    "seen_in": slug,
                })
        print(f"   nodes[{slug}] {s} — {len(nodes)} nodes: {kinds}")

    dump("catalog.json", catalog)
    print(f"[catalog] {len(catalog)} distinct (type:event_id) entries")

    # 4) config-schema for each distinct event_id
    schemas = {}
    for key, meta in catalog.items():
        eid = meta["event_id"]
        s, schema = hr.get(f"/events/{eid}/config-schema")
        schemas[key] = {"meta": meta, "status": s, "schema": schema}
        title = ""
        if isinstance(schema, dict):
            title = schema.get("title") or schema.get("name") or ""
        print(f"   schema {key} ({meta.get('example_name')}) -> {s} {title}")
    dump("event_schemas.json", schemas)
    print("Done. See workflow/discovery/*.json")


if __name__ == "__main__":
    main()
