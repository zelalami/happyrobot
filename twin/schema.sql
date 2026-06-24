-- HappyRobot FDE — Twin data layer
-- Canonical DDL for the carrier-sales operations dashboard.
-- Applied via the Public API (POST /twin/sql) by twin/10_create_tables.py — committed
-- here as the source of truth + rollback reference (Twin has no built-in schema versioning,
-- see happyrobot-docs/twin/using-in-apps.md "Use version control for App code, not Twin schema").
--
-- SECRECY: this table NEVER stores max_buy or a raw ceiling margin.
-- It carries only non-secret signals — posted_rate + agreed_rate (both non-secret),
-- ceiling_respected (bool, true-by-construction for any booked row: the adapter rejects
-- over-ceiling books), negotiation_rounds, and OTP outcome (verified + attempts, never the code).
-- The dashboard shows the agreed-vs-POSTED spread (non-secret), never agreed-vs-ceiling.

-- One row per completed call. PK = run_id, mapped to the __run_id__ runtime variable so the
-- run-dump performs INSERT ... ON CONFLICT DO UPDATE (idempotent on replay/backfill).
CREATE TABLE IF NOT EXISTS call_outcomes (
  run_id              uuid PRIMARY KEY,          -- __run_id__
  completed_at        timestamp,                 -- __completed_at__ (UTC)
  carrier_mc          text,                      -- MC collected on the call
  carrier_name        text,                      -- FMCSA legal/DBA name
  carrier_phone       text,                      -- masked registered number the OTP went to (never the code)
  authority_status    text,                      -- active | not_authorized | not_found | lookup_error (adapter emits active/not_authorized)
  otp_verified        boolean,                   -- adapter-confirmed mid-call before matching
  otp_attempts        int8,                      -- adapter-tracked attempts (brute-force pressure)
  lane                text,                       -- "Huntsville, AL -> Austin, TX"
  origin_state        text,
  dest_state          text,
  equipment           text,                       -- dry van | reefer | flatbed | step deck | power only
  load_id             text,                       -- TMS LOAD_ID pitched/booked
  posted_rate         float8,                     -- opening posted rate (non-secret)
  agreed_rate         float8,                     -- final booked rate (null unless booked)
  ceiling_respected   boolean,                    -- compliance proof; true-by-construction for booked rows
  negotiation_rounds  int8,                       -- carrier counter-rounds used (0-3; >3 must never occur)
  outcome             text,                       -- booked|negotiation_failed|no_authority|otp_failed|no_loads|carrier_declined|tms_error|abandoned
  decline_reason      text,                       -- why a non-booked call ended (null when booked)
  booking_ref         text,                       -- BOOKING_REF from LOAD_BOOK (null unless booked)
  handoff_mocked      boolean,                    -- mocked senior-rep handoff fired (booked calls only)
  transcript_url      text,
  recording_url       text,
  tms_fault_observed  text,                       -- timeout|partial|malformed|delayed_term|none
  notes               text,                       -- short outcome summary / anomaly note
  handle_time_s       int8                        -- call duration (seconds)
);

-- Recent-calls table sorts by completion desc; outcome powers KPI/funnel filters.
CREATE INDEX IF NOT EXISTS idx_call_outcomes_completed_at ON call_outcomes (completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_call_outcomes_outcome      ON call_outcomes (outcome);
