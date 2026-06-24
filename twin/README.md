# Twin data layer

The HappyRobot-native data layer for the carrier-sales workflow. One table,
`call_outcomes` (one row per completed call), populated by a **workflow run-dump** and read
**server-side only** by the [Apps dashboard](../apps-dashboard) through the Twin gateway.

Everything table-shaped is authored via the **Public API** as committed, idempotent scripts
(same approach as `workflow/`). The run-dump itself is configured once in the UI (no dump API
exists) — its spec is committed in [`DUMP_MAPPING.md`](DUMP_MAPPING.md).

## Files

| File | Purpose |
| --- | --- |
| `schema.sql` | Canonical DDL for `call_outcomes` (source of truth + rollback reference) |
| `10_create_tables.py` | Apply `schema.sql` via `POST /twin/sql` (idempotent). `--verify` prints columns |
| `30_seed.py` | Upsert clean, varied demo rows so the dashboard renders. `--clear` removes them |
| `40_discover.py` | Read-only spike: harvested the Twin/AI-Extract node contracts → `discovery/` |
| `DUMP_MAPPING.md` | The authoritative-writer spec: how to configure the run-dump + column→variable map |
| `_common.py` | Reuses `workflow/hrlib.py` + `workflow/.env` (single source of API auth) |

Run from the repo root: `python3 twin/10_create_tables.py --verify`, then `python3 twin/30_seed.py`.

## Key findings (discovery)

- **Twin tables are fully scriptable** (`/twin/tables`, `/twin/sql`, `/rows`, `/rows/bulk`).
  Types: `int8 · text · boolean · timestamp · uuid · jsonb · float8` (no `int4`/`float4`).
- **No "Write to Twin" node in the Public API** — it's UI-builder-only. The durable writer is
  therefore the **run-dump** (upsert on `__run_id__`; reliable because tools return 200+status).
- **AI-Extract is API-creatable** (event `01926f30…`; fields `prompt`/`input`/`parameters`/
  `json_schema`/`model`) and enriches the derived/boolean columns the dump can't transform.
- The org's Twin must be **provisioned** (Settings → Twin Database = Available) and the
  **gateway deployed** (status Running) before the table/dashboard work end-to-end.

## Secrecy

`call_outcomes` never stores `max_buy`, a raw ceiling, or an agreed-vs-ceiling margin. It
carries only non-secret signals. The dashboard shows `ceiling_respected` + the agreed-vs-**posted**
spread (both numbers non-secret), never agreed-vs-ceiling. See `schema.sql` header for detail.
