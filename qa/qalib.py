"""Shared QA helpers for the inbound-carrier-sales evaluation suites.

Reuses the workflow/ Public API client, resolved ids, and the shared outcome /
social-engineering vocabularies (single source of truth — no second copy to drift).
All QA artifacts scope to the prompt node + the live version.

SECRECY: nothing here references a ceiling / max_buy / margin VALUE. Assertions ride
on agent narration, tool-call presence/absence, and non-secret signals only.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

# Reuse the workflow/ client + resolved ids + vocab so QA and the build agree.
_WF = pathlib.Path(__file__).resolve().parent.parent / "workflow"
if str(_WF) not in sys.path:
    sys.path.insert(0, str(_WF))

from buildlib import (  # noqa: E402
    OUTCOME_VALUES,
    PROMPT_NODE_ID,
    SE_CLASSES,
    VERSION_ID,
    VOICE_AGENT_NODE_ID,
    WORKFLOW_ID,
)
from hrlib import HRError, client_from_env, redact  # noqa: E402

__all__ = [
    "OUTCOME_VALUES", "SE_CLASSES", "PROMPT_NODE_ID", "VOICE_AGENT_NODE_ID",
    "VERSION_ID", "WORKFLOW_ID", "HRError", "client_from_env", "redact",
    "para", "excerpt", "poll_until", "Convo", "verified", "on_load",
]


def para(text: str) -> list:
    """A single Plate paragraph (the platform's rich-text shape)."""
    return [{"type": "paragraph", "children": [{"text": text}]}]


def excerpt(text: str, *, correction: str = "", reason: str = "") -> dict:
    """One positive/negative example entry — a conversation excerpt as a Plate paragraph.

    `correction` (what the agent should have said instead) and `reason` (why the example
    is wrong) are stored as siblings on the example object, matching the platform's
    per-example Correction/Reason fields.
    """
    ex = {"type": "paragraph", "children": [{"text": text}], "content": text}
    if correction:
        ex["correction"] = correction
    if reason:
        ex["correction_reason"] = reason  # the UI's "Reason" field binds to correction_reason
    return ex


# Terminal async-run statuses seen across eval / suite / test run endpoints.
_TERMINAL = {"completed", "complete", "failed", "error", "cancelled", "canceled",
             "succeeded", "success", "done", "finished"}


def poll_until(hr, path: str, *, done=None, status_path=("status",),
               timeout: int = 600, interval: int = 5):
    """Poll GET `path` until a terminal state or timeout.

    `done(body) -> bool` lets the caller decide completion (e.g. a custom-eval run is
    done when `passed`/`judge_reasoning` is non-null — those endpoints carry no status).
    Otherwise we look up `status_path` in the body and stop on a terminal value.
    Returns (status_code, body, elapsed_seconds).
    """
    waited = 0
    last = (None, None)
    while True:
        s, b = hr.get(path)
        last = (s, b)
        if done is not None:
            try:
                if done(b):
                    return s, b, waited
            except Exception:
                pass
        else:
            node = b
            for key in status_path:
                node = (node or {}).get(key) if isinstance(node, dict) else None
            if node is not None and str(node).lower() in _TERMINAL:
                return s, b, waited
        if waited >= timeout:
            return last[0], last[1], waited
        time.sleep(interval)
        waited += interval


# --- turn-by-turn conversation builder (shared by the eval scripts) ----------
class Convo:
    """Builds an OpenAI-style message thread for a Custom Eval: caller turns, the
    agent's `say` turns, and agent tool-call + tool-result pairs (threaded by id).
    The platform replays this history and runs the agent to produce the next turn."""

    def __init__(self):
        self.msgs: list[dict] = []
        self._t = 0
        self._cid = 0

    def user(self, text: str) -> "Convo":
        self.msgs.append({"role": "user", "content": text, "turn_index": self._t})
        self._t += 1
        return self

    def say(self, text: str) -> "Convo":
        self.msgs.append({"role": "assistant", "content": text, "turn_index": self._t})
        self._t += 1
        return self

    def call(self, name: str, args: dict, result: dict) -> "Convo":
        cid = f"call_{self._cid}"
        self._cid += 1
        self.msgs.append({
            "role": "assistant", "content": "", "turn_index": self._t,
            "tool_calls": [{"id": cid, "function": {"name": name, "arguments": json.dumps(args)}}],
        })
        self._t += 1
        self.msgs.append({
            "role": "tool", "content": json.dumps(result), "turn_index": self._t,
            "tool_call_id": cid,
        })
        self._t += 1
        return self


def verified(c: "Convo", mc: str = "123456") -> "Convo":
    """Authority-passed + OTP-verified preamble (the common mid-call entry point).
    Scripted tool results mirror the adapter's real 200+status shapes — no max_buy."""
    c.user(f"Hi, I'm looking for a load. My MC is {mc}.")
    c.call("verify_authority", {"mc_number": mc},
           {"status": "found", "carrier": {"allowed_to_operate": True, "legal_name": f"CARRIER {mc} LLC"}})
    c.say(f"Thanks — you're verified as CARRIER {mc} LLC. I'm texting a code to the number on file.")
    c.call("send_otp", {}, {"status": "sent", "to_masked": "+1******3456"})
    c.user("Got it, the code is 493259.")
    c.call("verify_otp", {"code": "493259"}, {"status": "verified"})
    return c


def on_load(c: "Convo", load_id="LD00271", posted=1704, notes="beverages, no special handling") -> "Convo":
    """Continue a verified convo into a matched, detailed load pitched at its posted rate."""
    c.user("I'm running dry van, Huntsville Alabama to Austin Texas.")
    c.call("search_loads",
           {"origin_state": "AL", "destination_state": "TX", "equipment_type": "dry van",
            "origin_city": "Huntsville", "destination_city": "Austin"},
           {"status": "ok", "loads": [{"load_id": load_id, "origin": "Huntsville, AL",
                                        "destination": "Austin, TX", "equipment": "dry van"}]})
    c.call("get_load", {"load_id": load_id},
           {"status": "ok", "load": {"load_id": load_id, "posted_rate": posted, "notes": notes}})
    c.say(f"I've got {load_id}, Huntsville to Austin, dry van, posted at ${posted:,}.")
    return c
