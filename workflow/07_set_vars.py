"""Set the workflow-scoped env vars the tool webhooks reference.
Idempotent — patches if the key already exists, else creates. ADAPTER_API_KEY is
hidden in the UI. Reads the secret values from workflow/.env (never printed).
"""
from __future__ import annotations

from buildlib import WORKFLOW_ID
from hrlib import client_from_env, load_env


def main():
    env = load_env()
    hr = client_from_env(env)

    desired = [
        {"key": "ADAPTER_BASE_URL", "value": env["ADAPTER_BASE_URL"], "hidden": False},
        {"key": "ADAPTER_API_KEY", "value": env["ADAPTER_API_KEY"], "hidden": True},
        {"key": "BROKER_NAME", "value": "HappyRobot Logistics", "hidden": False},
        {"key": "REP_NAME", "value": "Sam", "hidden": False},
    ]

    s, body = hr.get(f"/workflows/{WORKFLOW_ID}/variables")
    existing = {}
    items = body if isinstance(body, list) else (body or {}).get("data", [])
    for v in items if isinstance(items, list) else []:
        if isinstance(v, dict):
            existing[v.get("key")] = v.get("id")
    print(f"[existing vars] {list(existing.keys())}")

    for d in desired:
        payload = {
            "key": d["key"],
            "value_production": d["value"],
            "value_staging": d["value"],
            "value_development": d["value"],
            "is_hidden_in_ui": d["hidden"],
        }
        if d["key"] in existing:
            vid = existing[d["key"]]
            s, r = hr.patch(f"/workflows/{WORKFLOW_ID}/variables/{vid}", payload)
            print(f"  PATCH {d['key']:18} -> {s}")
        else:
            s, r = hr.post(f"/workflows/{WORKFLOW_ID}/variables", payload)
            print(f"  POST  {d['key']:18} -> {s}")
            if s not in (200, 201):
                print(f"        {r}")


if __name__ == "__main__":
    main()
