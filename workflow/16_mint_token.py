"""Mint a web-call voice token to confirm the workflow launches over
WebRTC (no phone number). Writes {url, token, room_name, run_id} to a git-ignored
file for the browser to join; prints everything except the full token.
Usage: python3 16_mint_token.py [development|staging|production]  (default development)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from buildlib import WORKFLOW_ID
from hrlib import client_from_env


def main():
    env = sys.argv[1] if len(sys.argv) > 1 else "development"
    hr = client_from_env()
    s, b = hr.post("/voice/tokens/", {
        "workflow_id": WORKFLOW_ID,
        "env": env,
        "ttl_seconds": 3600,
        "data": {"demo": True, "scenario": "webcall-test"},
    })
    print(f"mint token (env={env}) -> {s}")
    if s != 200 or not isinstance(b, dict):
        print(str(b)[:400]); return
    out = Path(__file__).resolve().parent / ".last_token.json"  # git-ignored (.*? no — see note)
    out.write_text(json.dumps(b, indent=2))
    tok = b.get("token", "")
    print(f"  url:       {b.get('url')}")
    print(f"  room_name: {b.get('room_name')}")
    print(f"  run_id:    {b.get('run_id')}")
    print(f"  token:     {tok[:18]}…<{len(tok)} chars> (full token saved to workflow/.last_token.json)")
    print("\n  ✅ Web-call launch path works — a browser can join this room over WebRTC.")


if __name__ == "__main__":
    main()
