import Link from "next/link";
import { requireAppUser } from "@/lib/auth";
import { getCallOutcomes } from "@/lib/calls";
import { deriveCeilingRespected, deriveOutcome, usd } from "@/lib/kpis";
import { OutcomeBadge, BoolBadge, AuthorityBadge, TopNav } from "@/components/ui";
import type { CallOutcome } from "@/lib/types";
import "../dash.css";

export const dynamic = "force-dynamic";

const OUTCOME_FILTERS = [
  "all",
  "booked",
  "negotiation_failed",
  "no_authority",
  "otp_failed",
  "no_loads",
  "carrier_declined",
  "abandoned",
];

export default async function CallsPage({
  searchParams,
}: {
  searchParams: Promise<{ outcome?: string; otp?: string }>;
}) {
  await requireAppUser();
  const sp = await searchParams;
  const outcomeFilter = sp.outcome ?? "all";
  const otpFilter = sp.otp ?? "all";

  let rows: CallOutcome[] = [];
  let error: string | null = null;
  try {
    rows = await getCallOutcomes(500);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const filtered = rows.filter((r) => {
    if (outcomeFilter !== "all" && deriveOutcome(r) !== outcomeFilter) return false;
    if (otpFilter === "verified" && r.otp_verified !== true) return false;
    if (otpFilter === "unverified" && r.otp_verified === true) return false;
    return true;
  });

  return (
    <main className="dash">
      <TopNav active="calls" />
      <h1>Recent Calls</h1>
      <p className="muted">
        {filtered.length} of {rows.length} calls · newest first
      </p>

      {error ? <div className="banner bad">Twin read error: {error}</div> : null}

      <div className="row-gap filter-row">
        <span className="muted">Outcome:</span>
        {OUTCOME_FILTERS.map((o) => (
          <Link
            key={o}
            href={`/calls?outcome=${o}${otpFilter !== "all" ? `&otp=${otpFilter}` : ""}`}
            className={`badge ${o === outcomeFilter ? "good" : "muted"}`}
          >
            {o.replace(/_/g, " ")}
          </Link>
        ))}
      </div>
      <div className="row-gap filter-row">
        <span className="muted">OTP:</span>
        {["all", "verified", "unverified"].map((v) => (
          <Link
            key={v}
            href={`/calls?otp=${v}${outcomeFilter !== "all" ? `&outcome=${outcomeFilter}` : ""}`}
            className={`badge ${v === otpFilter ? "good" : "muted"}`}
          >
            {v}
          </Link>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="panel muted">No calls match.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Completed</th>
                <th>MC</th>
                <th>Carrier</th>
                <th>Lane</th>
                <th>Equip</th>
                <th>Authority</th>
                <th>OTP</th>
                <th className="num">Rounds</th>
                <th className="num">Agreed</th>
                <th>Ceiling</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.run_id}>
                  <td>
                    <Link href={`/calls/${r.run_id}`} className="back-link">
                      {fmtTs(r.completed_at)}
                    </Link>
                  </td>
                  <td>{r.carrier_mc ?? "—"}</td>
                  <td>{r.carrier_name ?? "—"}</td>
                  <td>{r.lane ?? "—"}</td>
                  <td>{r.equipment ?? "—"}</td>
                  <td><AuthorityBadge status={r.authority_status} /></td>
                  <td><BoolBadge value={r.otp_verified} /></td>
                  <td className="num">{r.negotiation_rounds ?? "—"}</td>
                  <td className="num">{usd(r.agreed_rate)}</td>
                  <td><BoolBadge value={deriveCeilingRespected(r)} trueLabel="ok" falseLabel="BREACH" /></td>
                  <td><OutcomeBadge outcome={deriveOutcome(r)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

function fmtTs(ts: string | null): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
