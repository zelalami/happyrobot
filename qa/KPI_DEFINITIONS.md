# KPI definitions — reconciled with the shipped dashboard

This note reconciles the originally-planned KPI definitions (written before the live
build) with what the operations dashboard **actually computes** (`apps-dashboard/src/lib/kpis.ts`)
over the Twin `call_outcomes` table (`twin/schema.sql`). Where they differ, the dashboard is the
source of truth — the plan predates the secrecy decision and the live data shapes.

There are **two distinct KPI families**, often conflated:
- **Behavioral Northstars** — LLM-judge standards on agent behavior (the seven northstars).
  Defined + graded under `qa/` (see `qa/10_northstars.py`, `qa/results/RESULTS.md`). Not in this table.
- **Business KPIs** — operational metrics over completed calls, shown on the dashboard. Reconciled below.

> **Secrecy is the headline divergence.** The original plan proposed two ceiling-relative KPIs — *"Margin saved
> vs ceiling"* (`avg(ceiling − agreed_rate)`) and *"Avg agreed-vs-ceiling %"* (`avg(agreed_rate / ceiling)`).
> Both require a `ceiling`/`max_buy` column. The Twin table **deliberately has none** — the secret never
> enters the data layer. These two KPIs are **dropped** and replaced by the non-secret **agreed-vs-posted %**
> (`(agreed − posted) / posted`), which measures negotiation discipline against the *public* posted rate.

## Variable-name mapping (planned → live schema)

| Planned variable | Live `call_outcomes` column | Note |
|---|---|---|
| `call_outcome` (`booked\|no_loads\|nego_failed\|auth_fail\|otp_fail\|abandoned`) | `outcome` (`booked\|negotiation_failed\|no_authority\|otp_failed\|no_loads\|carrier_declined\|tms_error\|abandoned`) | superset; 8-value enum is the shared vocab (`buildlib.OUTCOME_VALUES`, the CallOutcome classifier, `extract_outcome`) |
| `fmcsa_passed` (bool) | `authority_status == 'active'` | derived, not a separate bool |
| `otp_verified` (bool) | `otp_verified` (bool) | same |
| `negotiation_rounds` (int) | `negotiation_rounds` (int8) | same |
| `agreed_rate` (num) | `agreed_rate` (float8) | same |
| `ceiling` (num, server-side) | **(absent — by design)** | secrecy: never written to Twin |
| `transferred` (bool) | `handoff_mocked` (bool) | the mocked senior-rep handoff |
| `handle_time_sec` | `handle_time_s` (int8) | same |

## KPI reconciliation

| Planned KPI | Dashboard field (`Kpis`) | Status | Formula actually computed | Target |
|---|---|---|---|---|
| Verification rate | `otp_verified_rate` | ✅ matches | `count(otp_verified) / count(authority_status='active')` | ≥ 95% |
| FMCSA pass rate | `authority_pass_rate` | 🔁 denom reconciled | `count(active) / count(authority_status not null)` — over calls that *reached* the check, not all calls | informational |
| Booking / commit rate | `booking_rate` | 🔁 denom reconciled | `count(booked) / count(*)` — over **all** calls (overall conversion), not just verified | ≥ 35% of verified |
| Margin saved vs ceiling | — | ❌ dropped (secrecy) | replaced by agreed-vs-posted | — |
| Avg agreed-vs-ceiling % | `avg_agreed_vs_posted_pct` | 🔁 replaced (secrecy) | `avg((agreed − posted)/posted × 100)` over booked — vs the **public posted** rate | report % |
| Avg negotiation rounds | `avg_negotiation_rounds` | 🔁 scope reconciled | `avg(negotiation_rounds)` over **booked** rows | ≤ 2.0 (≤3 cap) |
| Avg handle time | `avg_handle_time_s` | ✅ matches | `avg(handle_time_s)` | ≤ 240s |
| Containment rate | *(derive from `outcome_breakdown`)* | ⚠️ not a tile | `count(outcome in booked,no_loads,negotiation_failed,no_authority,carrier_declined) / count(*)` | ≥ 90% |
| Negotiation-fail rate | *(derive from `outcome_breakdown`)* | ⚠️ not a tile | `count(negotiation_failed) / count(otp_verified)` | ≤ 25% |
| False-transfer rate (guardrail) | `anomalies.false_transfer` | ✅ **added** | `count(handoff_mocked AND booking_ref IS NULL)` | **0** |

**Compliance anomalies** (`anomalies`, all must be 0):
`matched_without_otp` (a load/booking with `otp_verified ≠ true`), `ceiling_breached`
(`ceiling_respected === false` on booked — never true by construction), `rounds_over_cap`
(`negotiation_rounds > 3`), and the newly-added `false_transfer` (handoff without a booking, alarms N10).

## Notes on specific tiles

- **`ceiling_respected_rate`** — `deriveCeilingRespected()` (`kpis.ts`) treats a booked row as
  ceiling-respected by construction (the adapter's server-side guard rejects any book above the
  hidden ceiling), so a null-on-booked value reads `true`. This fix is in the committed source but
  the deployed dashboard predates it (live tile reads 66.7% until the sandbox redeploy).
- **Containment / negotiation-fail** are computable today from `outcome_breakdown` but are not yet
  dedicated tiles; the data supports them with no schema change.
- **No secret is ever divided, subtracted, or charted** — every KPI uses non-secret signals
  (`posted_rate`, `agreed_rate`, `outcome`, `otp_verified`, `negotiation_rounds`, `handoff_mocked`).
