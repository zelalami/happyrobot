"""Add the post-call AI-Extract node to inbound-carrier-sales.

The run-dump writes node *outputs* only, so tool params + nested webhook responses
dump as NULL. This node is the no-adapter-change source for the per-call business
fields: it reads the voice agent's `transcript` output and emits them as the
`extract_outcome.*` node output, which the run-dump can then bind.

It runs AFTER the call (a child of the Inbound Voice Agent, sibling of the prompt
which sits at sort_index -1), so it never touches the live conversation.

Idempotent: deletes any existing `extract_outcome` node, then creates it fresh and
reads the stored configuration back to confirm the platform normalized it.

    python3 workflow/22_add_extract.py
"""
from __future__ import annotations

import json

from buildlib import (EVENT, EXTRACT_NODE_NAME, VERSION_ID, VOICE_AGENT_NODE_ID,
                      extract_config)
from hrlib import client_from_env


def show_tree(nodes):
    by_parent = {}
    for n in nodes:
        by_parent.setdefault(n.get("parent_id"), []).append(n)

    def walk(pid, d=0):
        for n in sorted(by_parent.get(pid, []), key=lambda x: x.get("sort_index", 0)):
            print("   " * d + f"- [{n.get('type')}] {n.get('name')}  si={n.get('sort_index')}")
            walk(n["id"], d + 1)

    walk(None)


def main():
    hr = client_from_env()

    # 0) A published (live) version is locked; unpublish before editing.
    #    NOTE: this leaves dev unpublished — republish is a separate, gated step
    #    (workflow/13_publish.py development) done once the node is reviewed.
    s, _ = hr.post(f"/versions/{VERSION_ID}/unpublish", {})
    print(f"unpublish dev (to unlock for edit) -> {s}")

    # 1) Idempotency — remove any prior extract node.
    s, b = hr.get(f"/versions/{VERSION_ID}/nodes")
    nodes = b["data"]
    for n in nodes:
        if n.get("name") == EXTRACT_NODE_NAME:
            ds, _ = hr.delete(f"/versions/{VERSION_ID}/nodes/{n['id']}")
            print(f"DELETE existing {EXTRACT_NODE_NAME} {n['id']} -> {ds}")

    # 2) Create the AI-Extract node as a post-call child of the voice agent.
    node = {
        "type": "action",
        "name": EXTRACT_NODE_NAME,
        "event_id": EVENT["ai_extract"],
        "parent_node_id": VOICE_AGENT_NODE_ID,
        "configuration": extract_config(VOICE_AGENT_NODE_ID),
    }
    s, body = hr.post(f"/versions/{VERSION_ID}/nodes", {"nodes": [node]})
    print(f"\nCREATE {EXTRACT_NODE_NAME} -> {s}")
    if s not in (200, 201):
        print(json.dumps(body, indent=2)[:2500])
        return
    new_id = body["data"][0]["id"]
    print(f"  node id: {new_id}  parent: {VOICE_AGENT_NODE_ID}")

    # 3) Read it back and confirm normalization (input var + parameters).
    s, rb = hr.get(f"/versions/{VERSION_ID}/nodes/{new_id}")
    nd = rb.get("data", rb) if isinstance(rb, dict) else {}
    cfg = nd.get("configuration") or {}
    print(f"\nread-back {s}: configuration keys = {list(cfg.keys())}")
    print("  input (normalized):", json.dumps(cfg.get("input"))[:300])
    params = cfg.get("parameters") or []
    print(f"  parameters: {len(params)} fields -> {[p.get('name') for p in params]}")
    print("  model:", json.dumps(cfg.get("model")) if cfg.get("model") else "(default gpt-4.1)")
    print("  prompt[:90]:", json.dumps(cfg.get("prompt"))[:120])

    # 4) Final graph.
    s, nb = hr.get(f"/versions/{VERSION_ID}/nodes")
    alln = nb["data"]
    print(f"\nFinal graph: {len(alln)} nodes")
    show_tree(alln)


if __name__ == "__main__":
    main()
