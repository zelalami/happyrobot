"""Publish the inbound-carrier-sales version to an environment.
Uses the version-level publish (test errors are informational, non-blocking).
Usage: python3 13_publish.py [development|staging|production]   (default: development)
"""
from __future__ import annotations

import json
import sys

from buildlib import VERSION_ID, WORKFLOW_ID
from hrlib import client_from_env


def main():
    env = sys.argv[1] if len(sys.argv) > 1 else "development"
    hr = client_from_env()
    s, b = hr.post(f"/versions/{VERSION_ID}/publish", {"environment": env})
    print(f"publish version -> {env} -> {s}")
    if isinstance(b, dict):
        te = b.get("test_errors")
        print("is_published:", b.get("is_published"), "| is_live:", b.get("is_live"),
              "| environment:", b.get("environment"))
        if te:
            print(f"\ntest_errors ({len(te) if isinstance(te,list) else '?'}) — informational:")
            print(json.dumps(te, indent=2)[:2000])
        else:
            print("no test_errors")
    else:
        print(str(b)[:400])

    # Confirm workflow now has a live production version.
    s, w = hr.get(f"/workflows/{WORKFLOW_ID}")
    if isinstance(w, dict):
        lv = w.get("latest_version") or {}
        print(f"\nworkflow slug={w.get('slug')} latest_version is_live={lv.get('is_live')} "
              f"published={lv.get('is_published')} env={lv.get('environment')}")


if __name__ == "__main__":
    main()
