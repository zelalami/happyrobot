# TMS Adapter

Integration layer for the HappyRobot inbound-carrier-sales PoC. It speaks the legacy
TMS's **raw‑TCP, fixed‑width, fault‑injecting** protocol outward and exposes a clean
**REST/JSON** surface inward to the HappyRobot voice workflow — and it is the single
trusted place that enforces the two secrets the LLM must never see: the **rate ceiling**
(`MAX_BUY`) and the **OTP**.

> Why an adapter exists at all: HappyRobot Custom Code nodes have no network access and
> Webhook nodes are HTTP‑only, so the TCP TMS can't be reached from the workflow. The
> adapter is the "integration layer built on top of it" — not an external DB or UI (Twin
> + Apps remain those).

## Security model (what the LLM physically cannot do)

- **Never leak / exceed the rate ceiling.** `MAX_BUY` is read from the TMS, cached
  server‑side, and **stripped from every load response**. Offers are evaluated by
  `services/ceiling.py`, which returns only `accept|counter|reject`. The counter is a pure
  function of `(posted_rate, round)` — provably independent of `max_buy` — so the spoken
  numbers carry no information about the ceiling. The ≤3‑round cap is owned by the adapter
  (`NegotiationStore`, keyed to `run_id`+`load_id`), so a caller can't reset rounds and
  binary‑search the ceiling.
- **Booking can't exceed or fabricate a deal.** `POST /bookings` books only a rate that
  (a) equals a rate the adapter itself recorded as `accept`ed for that run+load, and (b) is
  `≤ max_buy` — both checked server‑side at book time.
- **OTP can't be talked around.** Codes are CSPRNG, stored hashed (peppered, constant‑time
  compare), keyed to the server‑trusted `run_id` + bound `mc`, single‑use, with a sticky
  3‑attempt budget that resends never refill. The code is sent only to the FMCSA‑resolved
  registered number (never a caller‑supplied one) and never appears in any response or log.
- **Graceful degradation.** All four TMS fault classes (timeout / partial / malformed /
  delayed‑termination) are detected from the wire; reads retry within a deadline, and
  `LOAD_BOOK` is verified, never blindly retried.

## REST contract

All **tool endpoints are `POST` + JSON** and require `Authorization: Bearer $ADAPTER_API_KEY`
(when configured). They return **HTTP 200 with a `status` field** for every business *and*
infra outcome (so a tool Webhook never marks the HappyRobot run FAILED); only the health
checks use real HTTP codes.

| Method · Path | Request (JSON) | `status` values |
|---|---|---|
| `GET /healthz` | — | `ok` |
| `GET /readyz` | — | `ready` (200) · `not_ready` (503) — fires DEBUG_ECHO |
| `POST /carriers/find` | `{mc?, dot?}` | `found` · `not_found` · `fmcsa_unavailable` · `invalid_request` |
| `POST /loads/search` | `{origin_state?, origin_city?, destination_state?, destination_city?, equipment_type?, max_results?}` | `ok` (`loads[]`, ≤3) · `invalid_request` · `tms_unavailable` |
| `POST /loads/get` | `{load_id}` | `found` (`load`, `ceiling_available` bool, **no `max_buy`**) · `not_found` · `tms_unavailable` |
| `POST /offers/evaluate` | `{run_id, load_id, carrier_offer}` | `ok` (`decision`, `round`, `rounds_remaining`, `suggested_counter?`, `agreed_rate?`, `reason?`) · `invalid_request` · `ceiling_error` |
| `POST /offers/log` | `{run_id, load_id, carrier_offer, mc_number?, notes?}` | `logged` |
| `POST /otp/send` | `{run_id, mc}` | `sent` (`to_masked`, `expires_in`, `request_id`) · `rate_limited` · `mc_mismatch` · `no_registered_phone` · `not_found` |
| `POST /otp/verify` | `{run_id, mc, code}` | `verified` · `rejected` (`attempts_remaining`) · `locked_out` |
| `POST /bookings` | `{run_id, load_id, mc_number, agreed_rate}` | `booked` (`booking_ref`, `confirmed`) · `rate_not_accepted` · `rate_exceeds_ceiling` · `ceiling_unavailable` · `already_booked` · `booking_ambiguous` |

`max_buy`, the OTP code, and the TMS token never appear in any response or log.

## Configuration

Loaded from a gitignored `.env` locally, or the platform secret store in the cloud.
Secrets are `SecretStr` (kept out of logs/reprs); the TMS credentials have no defaults, so a
missing one fails the process at boot. See [`.env.example`](.env.example).

| Var | Required | Purpose |
|---|---|---|
| `TMS_HOST`, `TMS_PORT`, `TMS_TOKEN` | yes | legacy TMS endpoint + bearer secret |
| `FMCSA_SOURCE` | — | live FMCSA backend: `soda` (default, open data, no key) · `qcmobile` · `stub` |
| `FMCSA_API_KEY` | `qcmobile` only | QCMobile webKey (WAF‑blocked server‑to‑server today) |
| `FMCSA_SODA_APP_TOKEN` | — | optional Socrata token for the `soda` backend (raises rate limits) |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` | — | SMS (deferred — stub‑only for now) |
| `ADAPTER_API_KEY` | recommended | inbound bearer; if unset, auth is OFF (dev only) |
| `USE_STUBS` | — | `true` ⇒ FMCSA/SMS use deterministic stubs (default for tests/demo) |
| `TMS_DEADLINE_S` / `TMS_CONNECT_TIMEOUT_S` / `TMS_READ_TIMEOUT_S` | — | TCP tunables (8 / 3 / 6) |
| `OTP_TTL_S` / `OTP_MAX_ATTEMPTS` / `OTP_RESEND_MAX` / `NEGOTIATION_MAX_ROUNDS` | — | policy (300 / 3 / 3 / 3) |
| `LOG_LEVEL` | — | structlog level |

> SMS is **stub‑only** for now (real provider deferred); the `TwilioSmsSender` seam is in
> place. FMCSA's live path defaults to the **SODA open‑data API** (`data.transportation.gov`,
> no key, reachable server‑to‑server, MC lookup by docket). The keyed **QCMobile** API is
> selectable via `FMCSA_SOURCE=qcmobile`, but its AWS edge WAF returns an HTML 403 to
> non‑browser clients today (the webKey is valid — reproduced from three networks), so it is
> blocked server‑to‑server. `USE_STUBS=true` (default) keeps tests + the demo offline.

## Develop & test

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # full suite, no network required
```

The TMS client is tested against captured wire transcripts and an in‑process fake TMS that
reproduces every fault class; the security core is tested against an adversarial matrix.

> The captured fixtures and the ceiling tests reference sandbox `MAX_BUY` values purely to
> validate wire parsing and to assert the ceiling is never serialized into a response. These
> are sandbox test values, not production secrets, and the running system never exposes them to
> the voice agent, API responses, Twin, or the dashboard.

## Run locally (Docker)

```bash
TMS_TOKEN=<your-token> docker compose up --build   # adapter on :8000, FMCSA/SMS stubbed
curl localhost:8000/healthz
```

Compose talks to the live hosted TMS (it's a network service) with FMCSA/SMS stubbed, so no
FMCSA/Twilio accounts are needed.

## Deploy (Railway — one command)

Railway co‑locates with the TMS for lowest latency. [`infra/railway.json`](infra/railway.json)
builds from the `Dockerfile` and health‑checks `/healthz`.

```bash
railway up                              # build + deploy from the Dockerfile
railway variables --set TMS_TOKEN=… --set ADAPTER_API_KEY=… --set USE_STUBS=false
# FMCSA defaults to the keyless SODA backend. For QCMobile instead:
#   railway variables --set FMCSA_SOURCE=qcmobile --set FMCSA_API_KEY=…
```

Secrets are injected as env vars — never baked into the image (`.env` is `.dockerignore`d).
The container honours Railway's injected `$PORT`.
