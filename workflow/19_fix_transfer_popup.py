"""The mock_handoff Transfer Popup 500'd because Create Popup keys
on phone_number and rejected the non-phone sentinel. Re-apply a phone-shaped
fictional number, TEST the node (must no longer return Internal server error),
then republish dev. Unpublishes first (live versions are locked).
"""
from __future__ import annotations

import json

from buildlib import EVENT, VERSION_ID, transfer_popup_config
from hrlib import client_from_env


def main():
    hr = client_from_env()
    hr.post(f"/versions/{VERSION_ID}/unpublish", {})

    # locate the Transfer Popup action node (child of the mock_handoff tool)
    s, nb = hr.get(f"/versions/{VERSION_ID}/nodes")
    nodes = nb["data"]
    mh = next((n["id"] for n in nodes if n["type"] == "tool" and n["name"] == "mock_handoff"), None)
    tp = next((n["id"] for n in nodes if n["type"] == "action" and n.get("parent_id") == mh), None)
    print("transfer popup node:", tp)

    s, b = hr.put(f"/versions/{VERSION_ID}/nodes/{tp}",
                  {"type": "action", "event_id": EVENT["transfer_popup"],
                   "configuration": transfer_popup_config()})
    print("PUT config ->", s)

    # TEST the node — should no longer be Internal server error.
    s, b = hr.post(f"/versions/{VERSION_ID}/nodes/{tp}/test", {"environment": "development"})
    data = (b or {}).get("data", {}) if isinstance(b, dict) else {}
    inner = data.get("data") if isinstance(data, dict) else None
    print(f"TEST -> http {s}; node_status={data.get('error') or 'ok'}; data={json.dumps(inner)[:300]}")
    ok = isinstance(inner, dict) and "error" not in inner
    print("  => Transfer Popup creates cleanly" if ok else "  => STILL failing — inspect above")

    # Republish.
    s, b = hr.post(f"/versions/{VERSION_ID}/publish", {"environment": "development"})
    print(f"publish development -> {s}; is_live={b.get('is_live') if isinstance(b,dict) else '?'}")


if __name__ == "__main__":
    main()
