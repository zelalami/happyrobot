"""Inspect recent workflow runs: status, transcript, tool calls + adapter
responses, outcome. Dumps full JSON to discovery/runs/ and prints a summary.
Usage: python3 30_runs.py [n]   (default 2 most recent)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from buildlib import WORKFLOW_ID
from hrlib import client_from_env

OUT = Path(__file__).resolve().parent / "discovery" / "runs"
OUT.mkdir(parents=True, exist_ok=True)


def as_list(b, *ks):
    if isinstance(b, list):
        return b
    if isinstance(b, dict):
        for k in ("data", "items", "results", "runs", "nodes", *ks):
            if isinstance(b.get(k), list):
                return b[k]
    return []


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    hr = client_from_env()
    s, b = hr.get(f"/workflows/{WORKFLOW_ID}/runs?page_size=10")
    runs = as_list(b)
    print(f"GET runs -> {s}; {len(runs)} returned\n")
    for r in runs[:n]:
        rid = r.get("id") or r.get("run_id")
        env = r.get("execution_environment") or r.get("environment")
        print("=" * 70)
        print(f"RUN {rid}  env={env}  status={r.get('status')}  ts={r.get('timestamp')}")
        sd, detail = hr.get(f"/runs/{rid}")
        (OUT / f"{rid}_detail.json").write_text(json.dumps(detail, indent=2, ensure_ascii=False))
        sn, nodes = hr.get(f"/runs/{rid}/nodes")
        (OUT / f"{rid}_nodes.json").write_text(json.dumps(nodes, indent=2, ensure_ascii=False))
        nlist = as_list(nodes)

        # transcript: search node outputs for a 'transcript' field
        transcript = None
        for nd in nlist:
            data = (nd.get("node_output") or {}).get("data") if isinstance(nd.get("node_output"), dict) else nd.get("data")
            if isinstance(data, dict) and data.get("transcript") and data["transcript"] not in ("[]", ""):
                transcript = data["transcript"]
        if transcript:
            print("\n--- transcript ---")
            try:
                turns = json.loads(transcript) if isinstance(transcript, str) else transcript
                for t in turns:
                    role = t.get("role") or t.get("speaker") or "?"
                    txt = t.get("content") or t.get("text") or t.get("message") or ""
                    print(f"  {role}: {txt}")
            except Exception:
                print("  ", str(transcript)[:1500])

        # tool calls: action/webhook node outputs (adapter responses)
        print("\n--- tool calls / node outputs ---")
        for nd in nlist:
            nm = nd.get("name", "?")
            typ = nd.get("type")
            out = nd.get("node_output")
            data = out.get("data") if isinstance(out, dict) else None
            err = (out or {}).get("error") if isinstance(out, dict) else None
            if typ in ("action", "tool"):
                summ = ""
                if isinstance(data, dict):
                    # show adapter status + a few safe fields
                    keys = {k: data[k] for k in ("status", "decision", "verified", "allowed_to_operate",
                            "booking_ref", "rounds_remaining", "to_masked", "load", "loads", "legal_name")
                            if k in data}
                    summ = json.dumps(keys)[:300] if keys else json.dumps(data)[:200]
                print(f"  [{typ:6}] {nm}: status_field={summ or '∅'}{(' ERR='+str(err)) if err else ''}")
        print()


if __name__ == "__main__":
    main()
