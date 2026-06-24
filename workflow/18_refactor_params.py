"""Reduce agent-supplied params to one-per-value and wire downstream
tools to reuse earlier values via cross-tool refs (send_otp/verify_otp/book_load
reuse verify_authority.mc_number; evaluate/log/book reuse get_load.load_id).

Unpublish -> update each tool's function (params) + webhook body -> republish dev.
Idempotent: re-applies the buildlib specs onto the existing nodes by name.
"""
from __future__ import annotations

import json

from buildlib import (EVENT, MOCK_HANDOFF, TOOLS, VERSION_ID, msg_from_spec,
                      tool_function, webhook_child_config)
from hrlib import client_from_env


def main():
    hr = client_from_env()

    # 1) Unpublish (live versions are locked).
    s, _ = hr.post(f"/versions/{VERSION_ID}/unpublish", {})
    print(f"unpublish -> {s}")

    # 2) Map names -> ids.
    s, nb = hr.get(f"/versions/{VERSION_ID}/nodes")
    nodes = nb["data"]
    tool_id = {n["name"]: n["id"] for n in nodes if n["type"] == "tool"}
    child_id = {}
    for n in nodes:
        if n["type"] == "action" and n.get("parent_id") in tool_id.values():
            # map by parent tool name
            for tn, tid in tool_id.items():
                if n["parent_id"] == tid:
                    child_id[tn] = n["id"]
    print("tools:", list(tool_id))

    # 3) Update tool functions (params) + 4) webhook bodies.
    for t in [*TOOLS, MOCK_HANDOFF]:
        tid = tool_id.get(t["name"])
        if not tid:
            print(f"  ! {t['name']} missing"); continue
        params = [{"name": p[0], "description": p[1], "required": p[2], "example": p[3]}
                  for p in t.get("params", [])] or None
        fn = tool_function(t["desc"], params, msg_from_spec(t["msg"]))
        s, b = hr.put(f"/versions/{VERSION_ID}/nodes/{tid}", {"type": "tool", "name": t["name"], "function": fn})
        nparams = len(t.get("params", []))
        print(f"  tool {t['name']:18} PUT -> {s}  ({nparams} param{'s' if nparams!=1 else ''})")

    for t in TOOLS:
        wid = child_id.get(t["name"])
        if not wid:
            print(f"  ! {t['name']} webhook missing"); continue
        cfg = webhook_child_config(t["path"], t["body"], tool_id[t["name"]], tool_id)
        s, b = hr.put(f"/versions/{VERSION_ID}/nodes/{wid}",
                      {"type": "action", "event_id": EVENT["webhook_post"], "configuration": cfg})
        print(f"  hook {t['name']:18} PUT -> {s}  raw={cfg['body']['raw'][:88]}")
        if s != 200:
            print("    ", json.dumps(b)[:200])

    # 5) Republish.
    s, b = hr.post(f"/versions/{VERSION_ID}/publish", {"environment": "development"})
    print(f"\npublish development -> {s}; is_live={b.get('is_live') if isinstance(b,dict) else '?'}")


if __name__ == "__main__":
    main()
