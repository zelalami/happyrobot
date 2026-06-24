import type { CallOutcome, Kpis, Outcome } from "@/lib/types";

// Pure functions over a set of call_outcomes rows. No I/O.

const OUTCOMES: Outcome[] = [
  "booked",
  "negotiation_failed",
  "no_authority",
  "otp_failed",
  "no_loads",
  "carrier_declined",
  "tms_error",
  "abandoned",
];

/**
 * Outcome of a call. Prefer the stored `outcome` column; otherwise derive it from
 * the deterministic columns so the dashboard never blanks out before enrichment.
 */
export function deriveOutcome(r: CallOutcome): Outcome {
  if (r.outcome && OUTCOMES.includes(r.outcome as Outcome)) {
    return r.outcome as Outcome;
  }
  if (r.booking_ref || r.agreed_rate) return "booked";
  if (r.authority_status && r.authority_status !== "active") return "no_authority";
  if (r.otp_verified === false) return "otp_failed";
  if (r.negotiation_rounds && r.negotiation_rounds > 0) return "negotiation_failed";
  if (r.load_id == null && r.authority_status === "active") return "no_loads";
  return "abandoned";
}

const isBooked = (r: CallOutcome) => deriveOutcome(r) === "booked";

/**
 * Whether the hidden rate ceiling was respected. A booked row is compliant by
 * construction — the adapter rejects any book above the ceiling — so a booked
 * row counts as respected unless explicitly recorded false. The AI-Extract node
 * never reasons about a ceiling (secrecy), so it leaves this null; we derive it
 * here on read. Non-booked rows stay null (not applicable).
 */
export function deriveCeilingRespected(r: CallOutcome): boolean | null {
  if (r.ceiling_respected != null) return r.ceiling_respected;
  return isBooked(r) ? true : null;
}
const reachedOtp = (r: CallOutcome) => r.authority_status === "active";
const authorityAttempted = (r: CallOutcome) => r.authority_status != null;

function avg(nums: number[]): number | null {
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
}
function rate(numer: number, denom: number): number | null {
  return denom > 0 ? numer / denom : null;
}

export function computeKpis(rows: CallOutcome[]): Kpis {
  const booked = rows.filter(isBooked);

  const outcome_breakdown: Record<string, number> = {};
  for (const r of rows) {
    const o = deriveOutcome(r);
    outcome_breakdown[o] = (outcome_breakdown[o] ?? 0) + 1;
  }

  const agreedVsPosted = booked
    .filter((r) => r.agreed_rate != null && r.posted_rate)
    .map((r) => ((r.agreed_rate! - r.posted_rate!) / r.posted_rate!) * 100);

  return {
    total_calls: rows.length,
    authority_pass_rate: rate(
      rows.filter((r) => r.authority_status === "active").length,
      rows.filter(authorityAttempted).length,
    ),
    otp_verified_rate: rate(
      rows.filter((r) => r.otp_verified === true).length,
      rows.filter(reachedOtp).length,
    ),
    booking_rate: rate(booked.length, rows.length),
    avg_negotiation_rounds: avg(booked.map((r) => r.negotiation_rounds ?? 0)),
    avg_agreed_vs_posted_pct: avg(agreedVsPosted),
    ceiling_respected_rate: rate(
      booked.filter((r) => deriveCeilingRespected(r) === true).length,
      booked.length,
    ),
    avg_handle_time_s: avg(
      rows.filter((r) => r.handle_time_s != null).map((r) => r.handle_time_s!),
    ),
    outcome_breakdown,
    anomalies: {
      matched_without_otp: rows.filter(
        (r) => (r.load_id || r.booking_ref) && r.otp_verified !== true,
      ).length,
      ceiling_breached: booked.filter((r) => r.ceiling_respected === false).length,
      rounds_over_cap: rows.filter((r) => (r.negotiation_rounds ?? 0) > 3).length,
      // Guardrail KPI: a handoff/transfer fired without a booking should never happen
      // (the mocked handoff is for booked deals only). Must read 0.
      false_transfer: rows.filter((r) => r.handoff_mocked === true && !r.booking_ref).length,
    },
  };
}

// --- formatting helpers ----------------------------------------------------
export function pct(x: number | null, digits = 0): string {
  return x == null ? "—" : `${(x * 100).toFixed(digits)}%`;
}
export function signedPct(x: number | null, digits = 1): string {
  if (x == null) return "—";
  const s = x >= 0 ? "+" : "";
  return `${s}${x.toFixed(digits)}%`;
}
export function usd(x: number | null): string {
  return x == null ? "—" : `$${Math.round(x).toLocaleString("en-US")}`;
}
export function duration(s: number | null): string {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}m ${sec.toString().padStart(2, "0")}s`;
}
export function num(x: number | null, digits = 1): string {
  return x == null ? "—" : x.toFixed(digits);
}

/** Bucket the agreed-vs-posted spread for display (never a raw ceiling margin). */
export function spreadBucket(x: number | null): string {
  if (x == null) return "—";
  if (x <= 0) return "at/below posted";
  if (x < 3) return "0–3% over posted";
  if (x < 6) return "3–6% over posted";
  if (x < 10) return "6–10% over posted";
  return "10%+ over posted";
}
