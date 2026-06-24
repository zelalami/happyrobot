"""Author the full tool layer on inbound-carrier-sales.

Idempotent: deletes every node except the 3 core ones (Web call trigger, Inbound
Voice Agent, Carrier Sales Prompt), then recreates all tools + their child action
nodes from scratch. Two passes because a tool param is referenced downstream by
group_id = <that tool's node id>, only known after the tool is created.

Adapter contract is authoritative (tms-adapter/app/schemas.py):
  /carriers/find {mc}                          /loads/get {load_id}
  /otp/send {run_id, mc}                        /offers/evaluate {run_id, load_id, carrier_offer}
  /otp/verify {run_id, mc, code}                /offers/log {run_id, load_id, carrier_offer, notes?}
  /loads/search {origin_*, destination_*, equipment_type}
  /bookings {run_id, load_id, mc_number, agreed_rate}
mock_handoff -> Transfer Popup (no webhook). end_call -> built-in hangup (no node).
"""
from __future__ import annotations

import json

from buildlib import (EVENT, PROMPT_NODE_ID, VERSION_ID, VOICE_AGENT_NODE_ID,
                      WEB_CALL_NODE_ID, msg_ai, msg_fixed, msg_none, para, tool_node)
from hrlib import client_from_env

KEEP = {WEB_CALL_NODE_ID, VOICE_AGENT_NODE_ID, PROMPT_NODE_ID}

# --- Tool specs (param-bearing). Body tokens: "RUN"=current.run_id,
#     ("S", name)=string param, ("N", name)=numeric param (quoted; pydantic coerces) ---
TOOLS = [
    {
        "name": "verify_authority",
        "desc": ("Use immediately after the carrier gives their MC number, to confirm their FMCSA "
                 "operating authority. Required before identity verification or any load. Returns "
                 "whether they are allowed to operate, plus their legal name."),
        "params": [("mc_number", "The carrier's motor carrier (MC) number, digits only.", True, "123456")],
        "msg": msg_ai("Tell the caller you're pulling up their authority now.", "Let me pull up your authority."),
        "path": "/carriers/find",
        "body": [("mc", ("S", "mc_number"))],
    },
    {
        "name": "send_otp",
        "desc": ("Use right after authority passes to text a one-time verification code to the carrier's "
                 "registered number. The code is sent and checked server-side — you never see it. "
                 "Never use before authority passes."),
        "params": [("mc_number", "The same MC number you just verified, digits only.", True, "123456")],
        "msg": msg_fixed("I'm sending a verification code to the number we have on file now."),
        "path": "/otp/send",
        "body": [("run_id", "RUN"), ("mc", ("S", "mc_number"))],
    },
    {
        "name": "verify_otp",
        "desc": ("Use when the carrier reads back the code they received by text. Pass exactly the digits "
                 "they said. This is the ONLY way to verify identity — there is no skip."),
        "params": [("mc_number", "The same MC number you verified, digits only.", True, "123456"),
                   ("code", "The verification code the carrier read aloud, digits only.", True, "4821")],
        "msg": msg_none(),
        "path": "/otp/verify",
        "body": [("run_id", "RUN"), ("mc", ("S", "mc_number")), ("code", ("S", "code"))],
    },
    {
        "name": "search_loads",
        "desc": ("Use after identity is verified and you have the carrier's lane and equipment, to find "
                 "matching loads on the board. Returns up to three loads (no rates)."),
        "params": [("origin_city", "Origin city the carrier wants to depart from.", False, "Huntsville"),
                   ("origin_state", "Origin state, 2-letter code.", True, "AL"),
                   ("destination_city", "Destination city.", False, "Austin"),
                   ("destination_state", "Destination state, 2-letter code.", True, "TX"),
                   ("equipment_type", "Equipment type: dry van, reefer, flatbed, step deck, or power only.", True, "dry van")],
        "msg": msg_ai("Tell the caller you're checking the load board.", "Let me check the board for you."),
        "path": "/loads/search",
        "body": [("origin_city", ("S", "origin_city")), ("origin_state", ("S", "origin_state")),
                 ("destination_city", ("S", "destination_city")), ("destination_state", ("S", "destination_state")),
                 ("equipment_type", ("S", "equipment_type"))],
    },
    {
        "name": "get_load",
        "desc": "Use to pull full details for the single best-matching load before you pitch it.",
        "params": [("load_id", "The load id from the search results.", True, "LD00271")],
        "msg": msg_none(),
        "path": "/loads/get",
        "body": [("load_id", ("S", "load_id"))],
    },
    {
        "name": "evaluate_offer",
        "desc": ("Use EVERY time the carrier names a rate. Pass their number. Then say exactly what comes "
                 "back: accept it, make the counter it returns, or decline. You do not decide the rate."),
        "params": [("load_id", "The load id being negotiated.", True, "LD00271"),
                   ("carrier_offer", "The rate the carrier proposed, in whole US dollars, digits only.", True, "1850")],
        "msg": msg_none(),
        "path": "/offers/evaluate",
        "body": [("run_id", "RUN"), ("load_id", ("S", "load_id")), ("carrier_offer", ("N", "carrier_offer"))],
    },
    {
        "name": "log_offer",
        "desc": ("Use to record the final negotiation result on a load — the accepted rate after a booking, "
                 "or the last rate discussed when no deal is reached. Requires a load and a rate."),
        "params": [("load_id", "The load id.", True, "LD00271"),
                   ("carrier_offer", "The final rate discussed, in whole US dollars, digits only.", True, "1850"),
                   ("notes", "Short outcome note, e.g. 'booked' or 'failed_negotiation'.", False, "failed_negotiation")],
        "msg": msg_none(),
        "path": "/offers/log",
        "body": [("run_id", "RUN"), ("load_id", ("S", "load_id")),
                 ("carrier_offer", ("N", "carrier_offer")), ("notes", ("S", "notes"))],
    },
    {
        "name": "book_load",
        "desc": ("Use ONLY after evaluate_offer returned accept. Books the load at the agreed rate. Read the "
                 "returned booking reference back to the carrier clearly."),
        "params": [("load_id", "The load id to book.", True, "LD00271"),
                   ("mc_number", "The carrier's verified MC number, digits only.", True, "123456"),
                   ("agreed_rate", "The accepted rate, in whole US dollars, digits only.", True, "1850")],
        "msg": msg_fixed("Great — let me lock that in for you."),
        "path": "/bookings",
        "body": [("run_id", "RUN"), ("load_id", ("S", "load_id")),
                 ("mc_number", ("S", "mc_number")), ("agreed_rate", ("N", "agreed_rate"))],
    },
]

MOCK_HANDOFF = {
    "name": "mock_handoff",
    "desc": ("Use ONLY after a successful booking, to hand the carrier to a senior rep for paperwork. "
             "This is a mocked handoff — there is no real transfer. Never use without a booking."),
    "msg": msg_fixed("Perfect, connecting you with one of our senior reps now to finalize the paperwork."),
}


def render_token(tok, tool_id: str) -> str:
    if tok == "RUN":
        return '"{{current.run_id}}"'
    kind, name = tok
    return '"{{' + tool_id + "." + name + '}}"'  # quoted; pydantic coerces numerics


def raw_body(spec_body, tool_id: str) -> str:
    parts = [f'"{k}": {render_token(tok, tool_id)}' for k, tok in spec_body]
    return "{" + ", ".join(parts) + "}"


def main():
    hr = client_from_env()

    # 1) Read current graph, delete every non-core node (actions before tools).
    s, body = hr.get(f"/versions/{VERSION_ID}/nodes")
    nodes = (body or {}).get("data", [])
    to_del = [n for n in nodes if n.get("id") not in KEEP]
    for typ in ("action", "tool", "condition", "prompt"):  # leaf-ish first
        for n in to_del:
            if n.get("type") == typ:
                ds, _ = hr.delete(f"/versions/{VERSION_ID}/nodes/{n['id']}")
                print(f"  DELETE {n['type']:7} {n.get('name')!r:42} -> {ds}")

    # 2) PASS A — create all tool nodes (children of the prompt).
    tool_nodes = []
    for t in TOOLS:
        params = [{"name": p[0], "description": p[1], "required": p[2], "example": p[3]} for p in t["params"]]
        tool_nodes.append(tool_node(t["name"], t["desc"], params, message=t["msg"], parent_id=PROMPT_NODE_ID))
    tool_nodes.append(tool_node(MOCK_HANDOFF["name"], MOCK_HANDOFF["desc"], None,
                                message=MOCK_HANDOFF["msg"], parent_id=PROMPT_NODE_ID))
    s, body = hr.post(f"/versions/{VERSION_ID}/nodes", {"nodes": tool_nodes})
    print(f"\nPASS A create {len(tool_nodes)} tools -> {s}")
    if s not in (200, 201):
        print(json.dumps(body, indent=2)[:1500]); return
    created = body["data"]
    name_to_id = {}
    # response preserves request order
    for spec, node in zip([*TOOLS, MOCK_HANDOFF], created):
        name_to_id[spec["name"]] = node["id"]
    print("  tool ids:", json.dumps(name_to_id, indent=2))

    # 3) PASS B — create each tool's child action node.
    children = []
    for t in TOOLS:
        tid = name_to_id[t["name"]]
        cfg = {
            "url": para("{{env.ADAPTER_BASE_URL}}" + t["path"]),
            "contentType": "application/json", "authType": "bearer",
            "token": para("{{env.ADAPTER_API_KEY}}"),
            "ignore5XX": True, "xssProtection": True, "webhookSchemaVersion": 2,
            "body": {"schemaVersion": 2, "contentType": "application/json",
                     "raw": raw_body(t["body"], tid)},
        }
        # Name must not repeat the path (WAF blocks dup path token in url+name).
        children.append({"type": "action", "name": f"{t['name']} webhook",
                         "event_id": EVENT["webhook_post"], "parent_node_id": tid,
                         "configuration": cfg})
    # mock_handoff -> Transfer Popup child (non-dialable sentinel phone number)
    children.append({
        "type": "action", "name": "mock_handoff · Transfer Popup",
        "event_id": EVENT["transfer_popup"], "parent_node_id": name_to_id["mock_handoff"],
        "configuration": {
            "phone_number": para("web-call:{{current.run_id}}"),
            "enable_transfer_summary": True,
            "transfer_summary": para("Booked carrier load — identity verified by OTP. "
                                     "See the run for booking reference, MC, lane, and agreed rate."),
            "enable_transcript": False,
            "enable_feedback": True,
            "enable_ttl_days": True, "ttl_days": 10,
        },
    })
    s, body = hr.post(f"/versions/{VERSION_ID}/nodes", {"nodes": children})
    print(f"\nPASS B create {len(children)} child nodes -> {s}")
    if s not in (200, 201):
        print(json.dumps(body, indent=2)[:2000]); return

    # 4) Final graph dump.
    s, nb = hr.get(f"/versions/{VERSION_ID}/nodes")
    from pathlib import Path
    Path(__file__).resolve().parent.joinpath("discovery", "after_build_nodes.json").write_text(
        json.dumps(nb, indent=2, ensure_ascii=False))
    alln = nb["data"]
    print(f"\nFinal graph: {len(alln)} nodes")
    by_parent = {}
    for n in alln:
        by_parent.setdefault(n.get("parent_id"), []).append(n)
    def show(nid, depth=0):
        for n in by_parent.get(nid, []):
            print("   " * depth + f"- {n['type']:7} {n.get('name')!r}")
            show(n["id"], depth + 1)
    show(None)


if __name__ == "__main__":
    main()
