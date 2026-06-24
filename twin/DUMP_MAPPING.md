# Run-dump → `call_outcomes`

The durable per-call write is a **Workflow Run Dump** (Twin's "one row per completed run").
It upserts on the `run_id` primary key and fires on every **completed** run; because every
tool webhook returns `200 + status`, runs always complete, so no outcome row is silently lost.
The native "Write to Twin" node is not in the Public API and the dump is configured in the Twin
UI, so this file is its committed spec / source of truth (the dump has no other code artifact).

## How the run-dump resolves variables

The run-dump writes from **node *outputs*** — the values a node emits, exposed in the variable
picker per node. This has two consequences that shape the mapping:

- **Tool-node parameters are inputs, not outputs**, so the values the agent supplies to a tool
  (`mc_number`, `load_id`, `agreed_rate`, …) are **not** writable by the dump. Binding a column
  to a tool param dumps NULL even though the picker previews the build-time example value — this
  was the original bug.
- **Webhook (action) responses** expose only `Error` / `Status` / `Code` at the top level; the
  business fields nested under the response object (`carrier.*`, `load.*`) are not bindable.

So the run-dump fills the **run-level** columns directly (run id, completion time, call duration)
and fills every per-call **business** column from the **AI-Extract node `extract_outcome`**,
whose 18 structured fields are themselves node outputs the dump can bind. `extract_outcome` runs
post-call off the voice agent's `transcript` (see
[`workflow/22_add_extract.py`](../workflow/22_add_extract.py) and `workflow/buildlib.py`
`EXTRACT_FIELDS`). The dump and that node ship together.

**The AI-Extract node wraps its extracted fields under a `response` object.** Its outputs are
`prompt` (the prompt echo), `response.*` (the 18 extracted fields — shown in the picker as
*Response Carrier Mc*, *Response Outcome*, …), and `llm_usage.*` (6 token-usage metadata fields).
**Bind only the 18 `response.*` fields**; never map `prompt` or `llm_usage.*` (noise). Selecting
the whole node in *Batch add variables* grabs all 25 — delete the `prompt` row and the 6
`llm_usage` rows afterward.

## Column → variable bindings

The dump-managed table is **recreated** (there is no attach-to-existing or edit-bindings flow —
the builder only offers *Create Workflow Dump Table*), so all three groups below are configured
in one pass. Set the column **Type** as listed; Twin coerces the AI-Extract string outputs into
the numeric/boolean columns.

### Run-level (dump runtime + voice-agent output)

| Column | Type | Variable Reference |
| --- | --- | --- |
| `run_id` | text (**PK**) | **Workflow Run ID** (*Add workflow run_id PK*) |
| `completed_at` | timestamp | **Completion Timestamp** |
| `handle_time_s` | int | `Inbound Voice Agent` → **Duration** |

### Business (← `extract_outcome` node outputs)

Bind each via the `@` picker (or **Batch add variables** → expand **extract_outcome** → select
the 18 **Response** fields → *Add columns*, then rename each from the auto-generated
`extract_outcome_response` to the bare name below and set its type). The picker label for each is
*Response <Field>*; the resolved reference is `extract_outcome.response.<field>`.

| Column | Type | Variable Reference | Picker label |
| --- | --- | --- | --- |
| `carrier_mc` | text | `extract_outcome.response.carrier_mc` | Response Carrier Mc |
| `carrier_name` | text | `extract_outcome.response.carrier_name` | Response Carrier Name |
| `authority_status` | text | `extract_outcome.response.authority_status` | Response Authority Status |
| `otp_verified` | boolean | `extract_outcome.response.otp_verified` | Response Otp Verified |
| `otp_attempts` | int8 | `extract_outcome.response.otp_attempts` | Response Otp Attempts |
| `lane` | text | `extract_outcome.response.lane` | Response Lane |
| `origin_state` | text | `extract_outcome.response.origin_state` | Response Origin State |
| `dest_state` | text | `extract_outcome.response.dest_state` | Response Dest State |
| `equipment` | text | `extract_outcome.response.equipment` | Response Equipment |
| `load_id` | text | `extract_outcome.response.load_id` | Response Load Id |
| `posted_rate` | float8 | `extract_outcome.response.posted_rate` | Response Posted Rate |
| `agreed_rate` | float8 | `extract_outcome.response.agreed_rate` | Response Agreed Rate |
| `negotiation_rounds` | int8 | `extract_outcome.response.negotiation_rounds` | Response Negotiation Rounds |
| `booking_ref` | text | `extract_outcome.response.booking_ref` | Response Booking Ref |
| `handoff_mocked` | boolean | `extract_outcome.response.handoff_mocked` | Response Handoff Mocked |
| `decline_reason` | text | `extract_outcome.response.decline_reason` | Response Decline Reason |
| `outcome` | text | `extract_outcome.response.outcome` | Response Outcome |
| `notes` | text | `extract_outcome.response.notes` | Response Notes |

### Not bound by the dump (added via SQL; remain null)

These five are neither run-level nor transcript-derived, so they are added by the `ALTER` below
and stay null. The dashboard tolerates nulls. **`ceiling_respected` is intentionally never
extracted** — the AI-Extract node has no concept of a ceiling (secrecy); it is derived
true-for-booked on read.

`carrier_phone` · `ceiling_respected` · `transcript_url` · `recording_url` · `tms_fault_observed`

## Configure (Twin UI — one time)

The `extract_outcome` node must be **published** first (the `@` picker only lists nodes from the
live version): `python3 workflow/13_publish.py development`.

1. **SQL Console** → `DROP TABLE IF EXISTS call_outcomes;`
2. **Create table ▾ → Workflow Dump Table**:
   - **Workflow** → `inbound-carrier-sales` (`9kegbd8rdw10`).
   - **Table name** → `call_outcomes`.
   - **Start with a primary key** → **Add workflow run_id PK** (`run_id` PK ← `Workflow Run ID`).
   - Add the two other **run-level** columns (`completed_at`, `handle_time_s`) per the table above.
   - **Batch add variables** → expand **extract_outcome** → select the 18 **Response** fields →
     *Add columns*; then **delete** the `extract_outcome_prompt` row and the 6 `extract_outcome_llm_usage*`
     rows (noise), and rename each remaining `extract_outcome_response` column to its bare name and
     set its type per the **Business** table above.
   - Leave **Also start a backfill** unchecked (historical runs predate the node, so they have no
     `extract_outcome` output — backfilling them would write all-null business rows).
   - **Create**.
3. **SQL Console** → add the five unmapped columns + indexes:

```sql
ALTER TABLE call_outcomes
  ADD COLUMN IF NOT EXISTS carrier_phone      text,
  ADD COLUMN IF NOT EXISTS ceiling_respected  boolean,
  ADD COLUMN IF NOT EXISTS transcript_url     text,
  ADD COLUMN IF NOT EXISTS recording_url      text,
  ADD COLUMN IF NOT EXISTS tms_fault_observed text;
```
```sql
CREATE INDEX IF NOT EXISTS idx_call_outcomes_completed_at ON call_outcomes (completed_at DESC);
```
```sql
CREATE INDEX IF NOT EXISTS idx_call_outcomes_outcome ON call_outcomes (outcome);
```

4. **`python3 twin/30_seed.py`** → reload the demo seed rows (idempotent upsert on `run_id`).

The full column set + types is mirrored in `twin/schema.sql`, the canonical DDL reference.

## Secrecy

There is **no `max_buy`, ceiling, or margin variable** anywhere in the carrier path, and the
`extract_outcome` schema is a closed 18-field set with no ceiling/margin field, so there is
nothing to map. `call_outcomes` carries only non-secret signals: `ceiling_respected` (bool, never
extracted), `negotiation_rounds`, `posted_rate` + `agreed_rate` (both non-secret), and the OTP
outcome (`otp_verified` + `otp_attempts`, never the code). Do not add any ceiling/margin column.
