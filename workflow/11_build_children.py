"""Create each tool's child action node, ONE request per child
(the 9-at-once batch tripped a Cloudflare WAF rule). Additive + idempotent:
looks up tool ids from the live graph and skips any tool that already has a child.
Retries on transient Cloudflare 403s.
"""
from __future__ import annotations

import json
from pathlib import Path

from buildlib import (EVENT, MOCK_HANDOFF, TOOLS, VERSION_ID, transfer_popup_config,
                      webhook_child_config)
from hrlib import client_from_env


def post_with_retry(hr, path, body, tries=5):
    for i in range(tries):
        s, b = hr.post(path, body)
        if s in (200, 201):
            return s, b
        blocked = isinstance(b, str) and "cloudflare" in b.lower()
        print(f"    attempt {i+1}: {s}{' (cloudflare 403)' if blocked else ''}")
        if not blocked and s != 403:
            return s, b  # real error — stop
    return s, b


def main():
    hr = client_from_env()
    s, body = hr.get(f"/versions/{VERSION_ID}/nodes")
    nodes = body["data"]
    name_to_id = {n["name"]: n["id"] for n in nodes if n["type"] == "tool"}
    has_child = {n["parent_id"] for n in nodes if n.get("parent_id")}
    print("tools:", list(name_to_id))

    plan = []
    for t in TOOLS:
        tid = name_to_id.get(t["name"])
        if not tid:
            print(f"  ! tool {t['name']} not found; run 10_build_tools first"); continue
        if tid in has_child:
            print(f"  = {t['name']}: child exists, skip"); continue
        # Node name must NOT repeat the URL path: a Cloudflare WAF rule blocks the
        # request when a path like "/offers/log" appears in BOTH url and node name.
        plan.append((t["name"], {
            "type": "action", "name": f"{t['name']} webhook",
            "event_id": EVENT["webhook_post"], "parent_node_id": tid,
            "configuration": webhook_child_config(t["path"], t["body"], tid),
        }))
    mh_id = name_to_id.get(MOCK_HANDOFF["name"])
    if mh_id and mh_id not in has_child:
        plan.append((MOCK_HANDOFF["name"], {
            "type": "action", "name": "mock_handoff · Transfer Popup",
            "event_id": EVENT["transfer_popup"], "parent_node_id": mh_id,
            "configuration": transfer_popup_config(),
        }))

    for name, node in plan:
        s, b = post_with_retry(hr, f"/versions/{VERSION_ID}/nodes", {"nodes": [node]})
        cid = (b.get("data") or [{}])[0].get("id") if isinstance(b, dict) else None
        print(f"  + {name:18} child -> {s} {cid or ''}")
        if s not in (200, 201):
            print("    ", json.dumps(b)[:300] if isinstance(b, dict) else str(b)[:200])

    # Final dump.
    s, nb = hr.get(f"/versions/{VERSION_ID}/nodes")
    Path(__file__).resolve().parent.joinpath("discovery", "after_build_nodes.json").write_text(
        json.dumps(nb, indent=2, ensure_ascii=False))
    alln = nb["data"]
    by_parent = {}
    for n in alln:
        by_parent.setdefault(n.get("parent_id"), []).append(n)

    def show(nid, depth=0):
        for n in by_parent.get(nid, []):
            print("   " * depth + f"- {n['type']:7} {n.get('name')!r}")
            show(n["id"], depth + 1)

    print(f"\nFinal graph: {len(alln)} nodes")
    show(None)


if __name__ == "__main__":
    main()
