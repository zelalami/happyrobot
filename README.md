# Inbound Carrier Sales Automation — HappyRobot FDE PoC

An AI voice agent that answers inbound freight-carrier calls end to end:
**FMCSA authority check → one-time-code identity verification → load match (legacy TMS) →
policy-bounded negotiation → booking → mocked senior-rep handoff → logged outcome.** Built
HappyRobot-native (voice workflow + Twin data layer + Apps dashboard) with an external **TMS Adapter**
that bridges the legacy raw-TCP TMS and enforces the two secrets the LLM must never see — the **rate
ceiling** and the **one-time-code**.

- **Adapter (live):** `https://tms-adapter-production.up.railway.app`
- **Workflow (development):** https://platform.happyrobot.ai/fdezakariaalami/workflows/9kegbd8rdw10/editor/s3d4nkrmppo4
- **Build doc:** [docs/BUILD_DOC.md](docs/BUILD_DOC.md)
## Architecture

```
Carrier (browser WebRTC)
   │
   ▼
HappyRobot workflow ── Web call → Inbound Voice Agent → Carrier Sales Prompt
   │                      ├─ 9 tools (Webhook POST, Bearer) ─────────────┐
   │                      └─ post-call extract_outcome (AI-Extract)      │
   │                                                                     ▼
   │                                          run-dump → Twin `call_outcomes` → Apps dashboard
   ▼
TMS Adapter (FastAPI, Railway) ── REST/JSON in · raw TCP out · ceiling + OTP enforced server-side
   ├─ Legacy TMS        (raw-TCP, fixed-width, fault-injecting)   — live
   ├─ FMCSA authority   (SODA federal open data, keyless)         — live
   └─ SMS               (stub; real provider deferred)            — mocked
```

Full architecture, security model, and QA results: **[docs/BUILD_DOC.md](docs/BUILD_DOC.md)**.

## Repo layout

| Path | What it is |
|---|---|
| [`tms-adapter/`](tms-adapter) | FastAPI service: TCP↔REST, ceiling + OTP enforcement, FMCSA/SMS. Has its own [README](tms-adapter/README.md). |
| [`workflow/`](workflow) | HappyRobot workflow, built via the Public API (idempotent scripts + exported definition in `export/`). [README](workflow/README.md) |
| [`twin/`](twin) | Twin `call_outcomes` schema + scripts + the run-dump binding map |
| [`apps-dashboard/`](apps-dashboard) | Next.js operations dashboard (overlay on the Apps template; reads Twin server-side). |
| [`qa/`](qa) | Northstars, custom evals, adversarial suites, KPI definitions, results, live-call evidence |
| [`docs/`](docs) | Build & operations document (the IT + business write-up) |

## Quickstart (adapter, local)

The adapter is the only locally-runnable component; the workflow, Twin, and dashboard live on the
HappyRobot platform. It talks to the **live hosted TMS** with FMCSA/SMS stubbed, so no FMCSA or SMS
accounts are needed locally.

```bash
cd tms-adapter
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q                       # full suite, no network required

TMS_TOKEN=<your-token> docker compose up --build    # adapter on :8000, FMCSA/SMS stubbed
curl localhost:8000/healthz                          # {"status":"ok"}
```

Cloud deploy is a single `railway up` (Dockerfile builder + `/healthz` health-check) — see
[`tms-adapter/README.md`](tms-adapter/README.md#deploy-railway--one-command).

## Security model

- **The rate ceiling and the one-time-code never reach the LLM.** They are read/held in the adapter;
  the workflow only ever sees `accept|counter|reject` decisions and a verified/not-verified result.
  Any counter offered is a pure function of the *public posted rate*, so spoken numbers leak nothing.
- **Booking is gated server-side:** the adapter books only a rate it recorded as accepted for that
  run+load **and** that is within the ceiling. The ≤3-round cap and OTP attempt budget are
  adapter-owned, so a caller cannot reset them.
- **Secrets are gitignored.** Only `.env.example` (names, no values) is committed. `ADAPTER_API_KEY`
  protects every endpoint; the TMS token, FMCSA key, ceiling value, and OTP code never appear in any
  response, log, repo file, or the demo. Cloud deploy injects secrets via the platform secret store.

## What's real vs mocked

| Real | Mocked / simulated |
|---|---|
| **FMCSA authority check** — live federal open data (SODA, `data.transportation.gov`, keyless, server-to-server) | **SMS code delivery** — stub only; OTP *logic* is real, only the channel is stubbed (code surfaced via a bearer-protected `GET /debug/outbox` for the demo) |
| **Legacy-TMS** raw-TCP integration (carrier, loads, booking) | **Senior-rep handoff** — simulated (browser web calls can't transfer; a phone deploy would warm-transfer) |
| **Booking** — real; a successful demo consumes a load | — |

## QA / evaluation

7 behavioral Northstars (100% audits enabled), 16/17 custom evals, hand-written + auto-generated
adversarial suites, and three captured live calls (happy / OTP-bypass / ceiling-probe) with a secrecy
scan. Summary: [`qa/SUMMARY.md`](qa/SUMMARY.md) · results: [`qa/results/`](qa/results) · KPI
definitions: [`qa/KPI_DEFINITIONS.md`](qa/KPI_DEFINITIONS.md).
