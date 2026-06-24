import { requireAppUser } from "@/lib/auth";
import { getCallOutcomes } from "@/lib/calls";
import { computeKpis, pct, num, signedPct, spreadBucket, duration } from "@/lib/kpis";
import { KpiCard, TopNav } from "@/components/ui";
import type { CallOutcome } from "@/lib/types";
import "./dash.css";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  await requireAppUser();

  let rows: CallOutcome[] = [];
  let error: string | null = null;
  try {
    rows = await getCallOutcomes(500);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const k = computeKpis(rows);
  const anomalyTotal =
    k.anomalies.matched_without_otp +
    k.anomalies.ceiling_breached +
    k.anomalies.rounds_over_cap +
    k.anomalies.false_transfer;

  return (
    <main className="dash">
      <TopNav active="overview" />
      <h1>Overview</h1>
      <p className="muted">Inbound carrier-sales — call outcomes &amp; KPIs from Twin.</p>

      {error ? <div className="banner bad">Twin read error: {error}</div> : null}

      <h2>Security &amp; compliance</h2>
      <div className="kpi-grid">
        <KpiCard label="Authority pass rate" value={pct(k.authority_pass_rate)} sub="FMCSA active / authority checks" />
        <KpiCard label="OTP-verified rate" value={pct(k.otp_verified_rate)} sub="verified / reached OTP" />
        <KpiCard
          label="Ceiling respected"
          value={pct(k.ceiling_respected_rate)}
          sub="of booked loads (must be 100%)"
          tone={k.ceiling_respected_rate === 1 || k.ceiling_respected_rate == null ? "good" : "bad"}
        />
        <KpiCard
          label="Compliance anomalies"
          value={String(anomalyTotal)}
          sub="OTP-skip / over-ceiling / >3 rounds  / false-transfer"
          tone={anomalyTotal === 0 ? "good" : "bad"}
        />
      </div>

      <h2>Conversion &amp; negotiation</h2>
      <div className="kpi-grid">
        <KpiCard label="Total calls" value={String(k.total_calls)} />
        <KpiCard label="Booking rate" value={pct(k.booking_rate)} sub="booked / total" />
        <KpiCard label="Avg negotiation rounds" value={num(k.avg_negotiation_rounds)} sub="booked loads (cap 3)" />
        <KpiCard
          label="Agreed vs posted"
          value={signedPct(k.avg_agreed_vs_posted_pct)}
          sub={spreadBucket(k.avg_agreed_vs_posted_pct)}
        />
        <KpiCard label="Avg handle time" value={duration(k.avg_handle_time_s)} />
      </div>

      <h2>Outcome breakdown</h2>
      <OutcomeBars breakdown={k.outcome_breakdown} />
    </main>
  );
}

function OutcomeBars({ breakdown }: { breakdown: Record<string, number> }) {
  const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    return <div className="panel muted">No calls yet.</div>;
  }
  const max = Math.max(...entries.map(([, c]) => c));
  return (
    <div className="panel">
      {entries.map(([outcome, count]) => (
        <div className="bar-row" key={outcome}>
          <div className="bar-label">{outcome.replace(/_/g, " ")}</div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(count / max) * 100}%` }} />
          </div>
          <div className="bar-count">{count}</div>
        </div>
      ))}
    </div>
  );
}
