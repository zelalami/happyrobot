"""Export the workflow definition into the repo.

Read-only. Writes workflow/export/:
  - workflow.json   : workflow meta (id, slug, latest version)
  - variables.json  : workflow env vars (ADAPTER_API_KEY value redacted)
  - nodes.json       : the full node graph (the authoritative definition)
  - graph.txt        : a human-readable tree of the node graph
This is the committable source-of-truth snapshot of the built workflow.
"""
from __future__ import annotations

import json
from pathlib import Path

from buildlib import VERSION_ID, WORKFLOW_ID
from hrlib import client_from_env

OUT = Path(__file__).resolve().parent / "export"
OUT.mkdir(exist_ok=True)


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def main():
    hr = client_from_env()

    s, wf = hr.get(f"/workflows/{WORKFLOW_ID}")
    dump("workflow.json", wf)
    print(f"workflow {s}: slug={wf.get('slug')}")

    s, vars_ = hr.get(f"/workflows/{WORKFLOW_ID}/variables")
    items = vars_ if isinstance(vars_, list) else (vars_ or {}).get("data", [])
    # Redact the VALUE of any UI-hidden (secret) variable — flag-based, so any
    # future secret is masked without needing to name it. variables.json is also
    # git-ignored (see .gitignore) so no values land in git regardless.
    for v in items if isinstance(items, list) else []:
        if isinstance(v, dict) and v.get("is_hidden_in_ui"):
            for k in ("value_production", "value_staging", "value_development"):
                if v.get(k):
                    v[k] = "***REDACTED***"
    dump("variables.json", items)
    print(f"variables {s}: {[v.get('key') for v in items] if isinstance(items,list) else items}")

    s, nb = hr.get(f"/versions/{VERSION_ID}/nodes")
    nodes = nb["data"]
    dump("nodes.json", nb)
    print(f"nodes {s}: {len(nodes)} nodes")

    # human-readable tree
    by_parent = {}
    for n in nodes:
        by_parent.setdefault(n.get("parent_id"), []).append(n)
    lines = []

    def tree(pid, d=0):
        for n in by_parent.get(pid, []):
            extra = ""
            if n["type"] == "action" and isinstance(n.get("configuration"), dict):
                url = n["configuration"].get("url")
                if isinstance(url, list):
                    txt = "".join(c.get("text", "") + (("{{" + c.get("group_id", "") + "." + c.get("variable_id", "") + "}}") if c.get("type") == "variable" else "") for c in url[0].get("children", []))
                    extra = f"   [{txt}]"
            lines.append("   " * d + f"- {n['type']:7} {n.get('name')}{extra}")
            tree(n["id"], d + 1)

    tree(None)
    (OUT / "graph.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nExported to {OUT}")


if __name__ == "__main__":
    main()
