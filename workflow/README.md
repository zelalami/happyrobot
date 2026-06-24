# HappyRobot voice workflow (`inbound-carrier-sales`)

The inbound carrier-sales voice agent, **built entirely through the HappyRobot Public API**
(reproducible, version-controlled) and consuming the live TMS adapter as its tools.

- **Workflow:** `inbound-carrier-sales` (slug `9kegbd8rdw10`)
- **Trigger:** **Web call** (browser WebRTC) — no phone number provisioned.
- **Adapter (tools backend):** `https://tms-adapter-production.up.railway.app`
- **Status:** built + exported; **not yet published** (see _Publishing & testing_).

## Node graph

```
Web call (trigger; to_number="web", no PSTN)
└─ Inbound Voice Agent   (voice "Josh HR"; freight keyterms; denoised STT; call-center ambience)
   └─ Carrier Sales Prompt   (prompt.md — ceiling secrecy, non-bypassable OTP, ≤3 rounds)
      ├─ verify_authority  → POST /carriers/find   {mc}
      ├─ send_otp          → POST /otp/send        {run_id, mc}
      ├─ verify_otp        → POST /otp/verify       {run_id, mc, code}
      ├─ search_loads      → POST /loads/search     {origin_*, destination_*, equipment_type}
      ├─ get_load          → POST /loads/get        {load_id}
      ├─ evaluate_offer    → POST /offers/evaluate  {run_id, load_id, carrier_offer}
      ├─ log_offer         → POST /offers/log       {run_id, load_id, carrier_offer}
      ├─ book_load         → POST /bookings         {run_id, load_id, mc_number, agreed_rate}
      └─ mock_handoff      → Transfer Popup (phone="web-call:{{run_id}}", non-dialable)
   └─ extract_outcome   → AI Extract (post-call; reads `transcript`, emits 18 business fields)
   end_call = built-in voice hangup (_hangup); no custom tool needed
```

`extract_outcome` runs **after** the call ends (a sibling of the prompt under the voice agent), so
it never touches the conversation. Its 18 transcript-derived fields feed the Twin run-dump — see
[`../twin/DUMP_MAPPING.md`](../twin/DUMP_MAPPING.md). Built by [`22_add_extract.py`](22_add_extract.py).

Every webhook sends `Authorization: Bearer {{use_case_variables.ADAPTER_API_KEY}}`,
`ignore5XX: true` (so an adapter business outcome never marks the run FAILED), and a JSON body
whose `{{current.run_id}}` + tool-param values are real Plate variable references.

## How it was built (scripts)

All scripts are dependency-free (stdlib `urllib`) and read creds from `workflow/.env`
(git-ignored). Run with `python3 workflow/<script>.py`.

| Script | Purpose |
|---|---|
| `hrlib.py` | Public API client (bearer auth, redaction) |
| `buildlib.py` | resolved ids, Plate helpers, tool specs (single source of truth) |
| `01_check.py` | auth + reachability spike |
| `02_discover.py` / `03_integrations.py` / `04_find_nodes.py` / `05_schemas.py` | harvest event_ids + config-schemas from the live platform (no guessing) |
| `06_calibrate.py` | calibrate one tool+webhook, learn the normalized shape |
| `07_set_vars.py` | set workflow env vars (`ADAPTER_BASE_URL`, `ADAPTER_API_KEY`, `BROKER_NAME`, `REP_NAME`) |
| `10_build_tools.py` | author all 9 tools + children (idempotent, full rebuild) |
| `11_build_children.py` | per-node child builder (additive, idempotent) |
| `12_update_prompt.py` | push `prompt.md` to the prompt node |
| `13_publish.py` | publish a version to an environment (gated — see below) |
| `20_export.py` | export the definition to `export/` (this deliverable) |

`export/` holds the committed snapshot: `workflow.json`, `nodes.json` (the authoritative graph),
and `graph.txt`. (`variables.json` is generated locally but git-ignored — it carries org ids and
the redacted secret; the variable *names* are listed above.) The build also writes a local
`discovery/` of harvested event_ids + config-schemas, which is git-ignored — scaffolding, not an artifact.

> **Note — org-specific:** these scripts are tied to this org/workflow: `workflow_id`,
> `version_id`, and node ids are hardcoded in `buildlib.py` from the live build, so they document
> *how* the workflow was constructed rather than running portably elsewhere. The portable
> deliverables are `export/nodes.json` (the definition) and the shareable workflow link.

## Key findings (resolved during the build)

- **Web-call trigger needs no phone number:** a first-class "Web call" trigger exists
  (`event_id 6e32e01e-…`); its output is `to_number:"web"`. A workflow still requires exactly
  one trigger node (the create/add-nodes API enforces it), and "Web call" is the right one — no
  PSTN number or "Inbound to Number" trigger needed.
- **Tool contracts follow the adapter's actual request models** (`tms-adapter/app/schemas.py`):
  real paths are `/carriers/find`, `/bookings`, `/offers/evaluate {carrier_offer}`,
  OTP `{run_id, mc}`, etc.
- **Tool-param references** embed as `{{<tool_node_id>.<param>}}` in webhook bodies (group_id =
  the tool's node id); the API converts `{{current.*}}`/`{{env.*}}`/`{{<id>.*}}` literals into
  proper Plate variable children automatically.
- **`log_offer` is scoped to load+offer states only** (booked / failed negotiation) because the
  adapter's `/offers/log` requires `load_id` + integer `carrier_offer`; non-load terminal states
  (no-authority, OTP-fail, no-match) are captured by the run + the CallOutcome classifier, with
  durable Twin logging handled by the data layer.
- **Cloudflare WAF gotcha:** a webhook create is 403-blocked when a path like `/offers/log`
  appears in BOTH the URL and the node *name* (LFI managed rule on a duplicated path token).
  Fix: node names omit the path (`"<tool> webhook"`).

## Publishing & testing

The workflow is published to the **development** environment. To run a live web call, a voice
token is minted (`POST /voice/tokens/ {workflow_id}`) and the browser joins over WebRTC (mic
required) — see [`TEST.md`](TEST.md) for the step-by-step. Production is intentionally left
unpublished.
