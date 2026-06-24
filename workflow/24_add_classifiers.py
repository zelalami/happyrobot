"""Add the real-time classifiers to the Inbound Voice Agent node.

Three classifiers run LIVE during the call (updating after each caller turn),
distinct from the post-call extract_outcome node:
  - the built-in Sentiment classifier (real_time_sentiment_classifier=true)
  - CallOutcome     — reuses the exact extract_outcome enum (one shared vocabulary)
  - SocialEngineering — tags the caller's manipulation behavior (OTP/ceiling/scope)

The voice-agent node config schema is shallow (real_time_classifiers is just typed
"array"), so we configure the doc shape ({name, prompt, classes}) and READ IT BACK to
confirm the platform stored it before republishing — the same safety pattern as the
extract node. Existing config keys (call/agent/keyterms/STT/...) are preserved untouched.

A published version is locked, so editing requires unpublish -> edit. By default this
script stops AFTER a verified read-back and leaves dev unpublished for review; pass
--publish to also republish development.

    python3 workflow/24_add_classifiers.py            # edit + verify, no republish
    python3 workflow/24_add_classifiers.py --publish  # edit + verify + republish dev
"""
from __future__ import annotations

import json
import sys

from buildlib import (CLASSIFIERS, EVENT, VERSION_ID, VOICE_AGENT_NODE_ID,
                      voice_agent_config_with_classifiers)
from hrlib import client_from_env


def main():
    do_publish = "--publish" in sys.argv[1:]
    hr = client_from_env()

    # 0) Read the live node config so the merge preserves every existing key.
    s, b = hr.get(f"/versions/{VERSION_ID}/nodes/{VOICE_AGENT_NODE_ID}")
    if s != 200:
        print(f"could not read voice-agent node -> {s}: {str(b)[:300]}")
        return
    nd = b.get("data", b)
    existing = nd.get("configuration") or {}
    print(f"voice-agent node type={nd.get('type')} event_id={nd.get('event_id')}")
    print(f"existing config keys: {list(existing.keys())}")

    new_cfg = voice_agent_config_with_classifiers(existing)

    # 1) Unlock for edit (a live version is locked).
    s, _ = hr.post(f"/versions/{VERSION_ID}/unpublish", {})
    print(f"\nunpublish dev (to unlock for edit) -> {s}")

    # 2) PUT the node with the merged configuration (preserve type discriminator).
    payload = {
        "type": nd.get("type", "action"),
        "event_id": nd.get("event_id", EVENT["inbound_voice_agent"]),
        "configuration": new_cfg,
    }
    s, body = hr.put(f"/versions/{VERSION_ID}/nodes/{VOICE_AGENT_NODE_ID}", payload)
    print(f"PUT voice-agent classifiers -> {s}")
    if s not in (200, 201):
        print(json.dumps(body, indent=2)[:2500])
        print("\nedit FAILED — dev left unpublished. Fix the classifier shape and re-run.")
        return

    # 3) Read back and confirm the platform stored the classifiers.
    s, rb = hr.get(f"/versions/{VERSION_ID}/nodes/{VOICE_AGENT_NODE_ID}")
    cfg = (rb.get("data", rb) if isinstance(rb, dict) else {}).get("configuration") or {}
    sentiment = cfg.get("real_time_sentiment_classifier")
    stored = cfg.get("real_time_classifiers") or []
    print(f"\nread-back {s}: sentiment={sentiment!r}, {len(stored)} custom classifier(s)")
    for c in stored:
        classes = c.get("classes")
        print(f"  - {c.get('name')!r}: classes={json.dumps(classes)[:160]} "
              f"prompt_keys={type(c.get('prompt')).__name__}")
    print("\nnormalized first classifier (full):")
    print(json.dumps(stored[0], indent=2)[:1200] if stored else "(none)")

    # 4) Verify the round-trip before any republish.
    want = {c["name"] for c in CLASSIFIERS}
    got = {c.get("name") for c in stored}
    ok = sentiment is True and want.issubset(got)
    print(f"\nround-trip verify: sentiment_on={sentiment is True} "
          f"classifiers_present={sorted(got)} -> {'OK' if ok else 'MISMATCH'}")
    if not ok:
        print("dev left unpublished — inspect the read-back above, adjust buildlib, re-run.")
        return

    if not do_publish:
        print("\nVerified. dev is unpublished. Re-run with --publish to republish development.")
        return

    s, pb = hr.post(f"/versions/{VERSION_ID}/publish", {"environment": "development"})
    print(f"\nrepublish development -> {s} | is_live={pb.get('is_live') if isinstance(pb, dict) else '?'}")
    te = pb.get("test_errors") if isinstance(pb, dict) else None
    print(f"test_errors: {len(te) if isinstance(te, list) else te or 'none'}")
    if te:
        print(json.dumps(te, indent=2)[:1500])


if __name__ == "__main__":
    main()
