"""Add ONE real tool (verify_authority) +
its POST webhook child to the existing prompt node, then read the stored config
back to learn the exact normalized shape before bulk-adding the other 9 tools.

This tool is real (the first of 10), not a throwaway. If the read-back shows the
shape is wrong, we delete the two nodes (printed ids) and retry.
"""
from __future__ import annotations

import json

from buildlib import PROMPT_NODE_ID, VERSION_ID, tool_node, webhook_post_node, msg_ai
from hrlib import client_from_env


def main():
    hr = client_from_env()

    nodes = [
        tool_node(
            name="verify_authority",
            description=(
                "Use immediately after the carrier gives their MC number, to confirm their "
                "FMCSA operating authority. Required before identity verification or loads. "
                "Returns whether they are allowed to operate plus their legal name."
            ),
            parameters=[{
                "name": "mc_number",
                "description": "The carrier's motor carrier (MC) number, digits only, e.g. 123456.",
                "required": True,
                "example": "123456",
            }],
            message=msg_ai("Tell the caller you're pulling up their authority now.",
                           example="Let me pull up your authority real quick."),
            parent_id=PROMPT_NODE_ID,
        ),
        webhook_post_node(
            name="verify_authority · POST /carriers/find",
            url="{{env.ADAPTER_BASE_URL}}/carriers/find",
            raw_body='{"run_id": "{{current.run_id}}", "mc": "{{mc_number}}"}',
            parent_index=0,
        ),
    ]

    print("POST /versions/{vid}/nodes  (tool verify_authority + webhook child)")
    s, body = hr.post(f"/versions/{VERSION_ID}/nodes", {"nodes": nodes})
    print(f"  -> {s}")
    print(json.dumps(body, indent=2)[:1500])
    if s not in (200, 201):
        print("  ABORT: add failed; nothing created (atomic).")
        return

    created = (body or {}).get("data", [])
    ids = [n.get("id") for n in created]
    print(f"  created node ids: {ids}")

    # Read the whole graph back and dump it for inspection.
    s, nodes_body = hr.get(f"/versions/{VERSION_ID}/nodes")
    from pathlib import Path
    Path(__file__).resolve().parent.joinpath("discovery", "after_calibrate_nodes.json").write_text(
        json.dumps(nodes_body, indent=2, ensure_ascii=False))
    allnodes = (nodes_body or {}).get("data", [])
    print(f"\n  version now has {len(allnodes)} nodes:")
    for n in allnodes:
        print(f"    - {n.get('type'):8} {n.get('name')!r}  id={n.get('id')} parent={n.get('parent_id')}")
    print("\n  -> stored config of the new tool + webhook written to "
          "discovery/after_calibrate_nodes.json")


if __name__ == "__main__":
    main()
