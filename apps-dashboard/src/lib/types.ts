// Shape of a call_outcomes row (mirrors the Twin table).
// NOTE: by design this type has NO max_buy / ceiling / raw-margin field — the
// secret never enters the data layer.
export interface CallOutcome {
  run_id: string;
  completed_at: string | null;
  carrier_mc: string | null;
  carrier_name: string | null;
  carrier_phone: string | null;
  authority_status: string | null;
  otp_verified: boolean | null;
  otp_attempts: number | null;
  lane: string | null;
  origin_state: string | null;
  dest_state: string | null;
  equipment: string | null;
  load_id: string | null;
  posted_rate: number | null;
  agreed_rate: number | null;
  ceiling_respected: boolean | null;
  negotiation_rounds: number | null;
  outcome: string | null;
  decline_reason: string | null;
  booking_ref: string | null;
  handoff_mocked: boolean | null;
  transcript_url: string | null;
  recording_url: string | null;
  tms_fault_observed: string | null;
  notes: string | null;
  handle_time_s: number | null;
}

export type Outcome =
  | "booked"
  | "negotiation_failed"
  | "no_authority"
  | "otp_failed"
  | "no_loads"
  | "carrier_declined"
  | "tms_error"
  | "abandoned"
  | "unknown";

export interface Kpis {
  total_calls: number;
  authority_pass_rate: number | null;
  otp_verified_rate: number | null;
  booking_rate: number | null;
  avg_negotiation_rounds: number | null;
  avg_agreed_vs_posted_pct: number | null;
  ceiling_respected_rate: number | null;
  avg_handle_time_s: number | null;
  outcome_breakdown: Record<string, number>;
  anomalies: {
    matched_without_otp: number;
    ceiling_breached: number;
    rounds_over_cap: number;
    false_transfer: number;
  };
}
