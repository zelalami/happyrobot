"""Verify the HappyRobot key + reachability before building.

Read-only. Confirms:
  1. HR_API_KEY authenticates (GET /workflows/ -> 200).
  2. The inbound-voice-agent template is available (GET /workflows/templates).
  3. The live adapter answers /healthz.
Prints NO secrets.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from hrlib import client_from_env, load_env


def main() -> None:
    env = load_env()
    hr = client_from_env(env)

    print("== 1) HappyRobot auth check: GET /workflows/ ==")
    status, body = hr.get("/workflows/")
    if status == 200:
        items = body if isinstance(body, list) else body.get("data", body)
        n = len(items) if isinstance(items, list) else "?"
        print(f"   OK 200 — key valid. Existing workflows: {n}")
    else:
        print(f"   FAIL {status}: {body}")
        return

    print("== 2) Templates: GET /workflows/templates ==")
    status, body = hr.get("/workflows/templates")
    if status == 200:
        items = body if isinstance(body, list) else body.get("data", body)
        names = []
        if isinstance(items, list):
            for t in items:
                if isinstance(t, dict):
                    names.append(t.get("slug") or t.get("name") or t.get("id"))
        print(f"   OK 200 — templates: {names or items}")
    else:
        print(f"   {status}: {body}")

    print("== 3) Adapter reachability: GET {ADAPTER_BASE_URL}/healthz ==")
    base = env.get("ADAPTER_BASE_URL", "").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=15) as resp:
            print(f"   OK {resp.status} — {resp.read().decode()[:120]}")
    except urllib.error.HTTPError as e:
        print(f"   HTTP {e.code} — {e.read().decode()[:120]}")
    except Exception as e:  # noqa: BLE001
        print(f"   Could not reach adapter: {e}")


if __name__ == "__main__":
    main()
