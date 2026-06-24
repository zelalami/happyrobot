"""Re-apply each webhook child's config with the string-model
body.raw ({{$var:groupId.variableId}} tokens) so raw stays a STRING and the
version is publish-valid. Idempotent: PUTs the corrected config onto the existing
webhook child of each tool.
"""
from __future__ import annotations

import json

from buildlib import EVENT, TOOLS, VERSION_ID, webhook_child_config
from hrlib import client_from_env


def main():
    hr = client_from_env()
    s, nb = hr.get(f"/versions/{VERSION_ID}/nodes")
    nodes = nb["data"]
    tool_by_name = {n["name"]: n for n in nodes if n["type"] == "tool"}
    child_of = {}
    for n in nodes:
        if n["type"] == "action" and n.get("parent_id"):
            child_of.setdefault(n["parent_id"], []).append(n)

    for t in TOOLS:
        tool = tool_by_name.get(t["name"])
        if not tool:
            print(f"  ! {t['name']}: tool not found"); continue
        kids = child_of.get(tool["id"], [])
        if not kids:
            print(f"  ! {t['name']}: no webhook child"); continue
        wid = kids[0]["id"]
        cfg = webhook_child_config(t["path"], t["body"], tool["id"])
        s, b = hr.put(f"/versions/{VERSION_ID}/nodes/{wid}",
                      {"type": "action", "event_id": EVENT["webhook_post"], "configuration": cfg})
        ok = s == 200
        # verify raw is a string
        rawtype = "?"
        if ok:
            s2, n2 = hr.get(f"/versions/{VERSION_ID}/nodes/{wid}")
            raw = (((n2 or {}).get("configuration") or {}).get("body") or {}).get("raw") if isinstance(n2, dict) else None
            rawtype = type(raw).__name__
        print(f"  {t['name']:18} PUT -> {s}  raw={rawtype}")
        if not ok:
            print("    ", json.dumps(b)[:200])


if __name__ == "__main__":
    main()
