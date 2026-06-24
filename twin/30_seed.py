"""Seed call_outcomes with clean, varied demo rows.

Idempotent (INSERT ... ON CONFLICT (run_id) DO UPDATE via /twin/sql). The seed
data is authored here (no external/LLM input), so building SQL literals directly
is injection-safe. Every row is CLEAN: ceiling_respected holds on booked rows,
no row exceeds 3 rounds, and no row reaches a load/booking without a verified OTP
— so the Compliance page shows zero anomalies. NEVER writes max_buy or a margin.

    python3 twin/30_seed.py            # upsert the seed rows
    python3 twin/30_seed.py --clear    # delete the seed rows (by their fixed run_ids)
"""
from __future__ import annotations

import sys
import time

from _common import client_from_env

# Fixed UUIDs so re-running upserts the same rows (and --clear can target them).
SEED = [
    dict(run_id="5e000000-0000-4000-8000-000000000001", completed_at="2026-06-22T14:58:11Z",
         carrier_mc="123456", carrier_name="CARRIER 123456 LLC", carrier_phone="+1******3456",
         authority_status="active", otp_verified=True, otp_attempts=1,
         lane="Huntsville, AL -> Austin, TX", origin_state="AL", dest_state="TX", equipment="dry van",
         load_id="LD00271", posted_rate=1704, agreed_rate=1800, ceiling_respected=True,
         negotiation_rounds=3, outcome="booked", decline_reason=None, booking_ref="KXSHQDE6DRUCGDO7",
         handoff_mocked=True, tms_fault_observed="none", handle_time_s=312,
         notes="seed: happy path, counter x2 then accept"),
    dict(run_id="5e000000-0000-4000-8000-000000000002", completed_at="2026-06-22T13:40:02Z",
         carrier_mc="445566", carrier_name="MERTZ TRUCKING CO", carrier_phone="+1******8821",
         authority_status="active", otp_verified=True, otp_attempts=1,
         lane="Dallas, TX -> Memphis, TN", origin_state="TX", dest_state="TN", equipment="reefer",
         load_id="LD00188", posted_rate=2100, agreed_rate=2150, ceiling_respected=True,
         negotiation_rounds=1, outcome="booked", decline_reason=None, booking_ref="QTM4ZP1W+R7K",
         handoff_mocked=True, tms_fault_observed="none", handle_time_s=198,
         notes="seed: quick accept near posted"),
    dict(run_id="5e000000-0000-4000-8000-000000000003", completed_at="2026-06-22T12:15:47Z",
         carrier_mc="778899", carrier_name="BNR ENTERPRISES INC", carrier_phone="+1******4410",
         authority_status="active", otp_verified=True, otp_attempts=2,
         lane="Atlanta, GA -> Nashville, TN", origin_state="GA", dest_state="TN", equipment="flatbed",
         load_id="LD00203", posted_rate=1500, agreed_rate=None, ceiling_respected=None,
         negotiation_rounds=3, outcome="negotiation_failed", decline_reason="negotiation_failed",
         booking_ref=None, handoff_mocked=False, tms_fault_observed="none", handle_time_s=276,
         notes="seed: carrier stayed above ceiling for 3 rounds; no transfer"),
    dict(run_id="5e000000-0000-4000-8000-000000000004", completed_at="2026-06-22T11:02:33Z",
         carrier_mc="999999", carrier_name="UNVERIFIED CARRIER", carrier_phone=None,
         authority_status="not_authorized", otp_verified=None, otp_attempts=None,
         lane=None, origin_state=None, dest_state=None, equipment=None,
         load_id=None, posted_rate=None, agreed_rate=None, ceiling_respected=None,
         negotiation_rounds=None, outcome="no_authority", decline_reason="no_authority",
         booking_ref=None, handoff_mocked=False, tms_fault_observed="none", handle_time_s=64,
         notes="seed: FMCSA authority not active; closed before OTP"),
    dict(run_id="5e000000-0000-4000-8000-000000000005", completed_at="2026-06-22T10:31:09Z",
         carrier_mc="222333", carrier_name="SCHNEIDER NATIONAL CARRIERS", carrier_phone="+1******1207",
         authority_status="active", otp_verified=False, otp_attempts=3,
         lane=None, origin_state=None, dest_state=None, equipment=None,
         load_id=None, posted_rate=None, agreed_rate=None, ceiling_respected=None,
         negotiation_rounds=None, outcome="otp_failed", decline_reason="otp_failed",
         booking_ref=None, handoff_mocked=False, tms_fault_observed="none", handle_time_s=142,
         notes="seed: OTP wrong x3, locked out; never reached load matching"),
    dict(run_id="5e000000-0000-4000-8000-000000000006", completed_at="2026-06-22T09:48:55Z",
         carrier_mc="334455", carrier_name="VT REEFER LINES", carrier_phone="+1******7788",
         authority_status="active", otp_verified=True, otp_attempts=1,
         lane="Billings, MT -> Burlington, VT", origin_state="MT", dest_state="VT", equipment="reefer",
         load_id=None, posted_rate=None, agreed_rate=None, ceiling_respected=None,
         negotiation_rounds=None, outcome="no_loads", decline_reason="no_matching_loads",
         booking_ref=None, handoff_mocked=False, tms_fault_observed="none", handle_time_s=121,
         notes="seed: verified carrier, no matching loads on lane/equipment"),
    dict(run_id="5e000000-0000-4000-8000-000000000007", completed_at="2026-06-22T08:20:14Z",
         carrier_mc="556677", carrier_name="LONE STAR HAULERS", carrier_phone="+1******9931",
         authority_status="active", otp_verified=True, otp_attempts=1,
         lane="Phoenix, AZ -> Denver, CO", origin_state="AZ", dest_state="CO", equipment="dry van",
         load_id=None, posted_rate=None, agreed_rate=None, ceiling_respected=None,
         negotiation_rounds=None, outcome="abandoned", decline_reason="caller_hangup",
         booking_ref=None, handoff_mocked=False, tms_fault_observed="none", handle_time_s=38,
         notes="seed: caller hung up mid-flow"),
]

COLUMNS = list(SEED[0].keys())


def lit(v) -> str:
    """Render a Python value as a safe SQL literal (seed data is trusted/static)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def run_sql(hr, sql: str, *, retries: int = 5):
    for attempt in range(retries):
        s, body = hr.post("/twin/sql", {"sql": sql})
        if s != 429:
            return s, body
        time.sleep(20 * (attempt + 1))
    return s, body


def main() -> None:
    hr = client_from_env()
    ids = ", ".join(lit(r["run_id"]) for r in SEED)

    if "--clear" in sys.argv:
        s, b = run_sql(hr, f"DELETE FROM call_outcomes WHERE run_id IN ({ids})")
        print(f"[{s}] cleared seed rows: {b.get('rowCount') if isinstance(b, dict) else b}")
        return

    cols = ", ".join(COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "run_id")
    ok = 0
    for r in SEED:
        vals = ", ".join(lit(r[c]) for c in COLUMNS)
        sql = (f"INSERT INTO call_outcomes ({cols}) VALUES ({vals}) "
               f"ON CONFLICT (run_id) DO UPDATE SET {updates}")
        s, b = run_sql(hr, sql)
        tag = (b.get("command") if isinstance(b, dict) else "") or ""
        print(f"  [{s}] {tag:7} {r['outcome']:18} {r.get('carrier_mc')}")
        if s in (200, 201):
            ok += 1
        else:
            print("    ERROR:", str(b)[:300])
    print(f"\nUpserted {ok}/{len(SEED)} seed rows.")


if __name__ == "__main__":
    main()
