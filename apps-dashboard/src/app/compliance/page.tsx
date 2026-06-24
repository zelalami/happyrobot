import Link from "next/link";
import { requireAppUser } from "@/lib/auth";
import { getCallOutcomes } from "@/lib/calls";
import { deriveOutcome } from "@/lib/kpis";
import { OutcomeBadge, TopNav } from "@/components/ui";
import type { CallOutcome } from "@/lib/types";
import "../dash.css";

export const dynamic = "force-dynamic";

// Every list here should be EMPTY. Any row means a safety invariant was violated.
const CHECKS: {
  key: string;
  title: string;
  desc: string;
  predicate: (r: CallOutcome) => boolean;
}[] = [
  {
    key: "otp",
    title: "Matched/booked without verified OTP",
    desc: "A load was pulled or booked but otp_verified ≠ true (OTP must be verified before any load matching).",
    predicate: (r) => Boolean(r.load_id || r.booking_ref) && r.otp_verified !== true,
  },
  {
    key: "ceiling",
    title: "Booked above ceiling",
    desc: "A booked row with ceiling_respected = false (a load booked above the hidden rate ceiling).",
    predicate: (r) => deriveOutcome(r) === "booked" && r.ceiling_respected === false,
  },
  {
    key: "rounds",
    title: "Negotiation exceeded 3 rounds",
    desc: "negotiation_rounds > 3 (negotiation must stop after at most 3 counter-rounds).",
    predicate: (r) => (r.negotiation_rounds ?? 0) > 3,
  },
  {
    key: "transfer",
    title: "Handoff fired without a booking",
    desc: "handoff_mocked = true but the call did not book (handoff/transfer should only follow a successful booking).",
    predicate: (r) => r.handoff_mocked === true && deriveOutcome(r) !== "booked",
  },
];

export default async function CompliancePage() {
  await requireAppUser();

  let rows: CallOutcome[] = [];
  let error: string | null = null;
  try {
    rows = await getCallOutcomes(500);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="dash">
      <TopNav active="compliance" />
      <h1>Compliance audit</h1>
      <p className="muted">Server-side enforcement evidence. Every section below should be empty.</p>
      {error ? <div className="banner bad">Twin read error: {error}</div> : null}

      {CHECKS.map((c) => {
        const hits = rows.filter(c.predicate);
        return (
          <section key={c.key}>
            <h2>{c.title}</h2>
            <p className="muted tight">{c.desc}</p>
            {hits.length === 0 ? (
              <div className="banner good">✓ No violations ({rows.length} calls checked).</div>
            ) : (
              <div className="banner bad">
                ✗ {hits.length} violation(s):
                <ul>
                  {hits.map((r) => (
                    <li key={r.run_id}>
                      <Link href={`/calls/${r.run_id}`} className="back-link">
                        {r.carrier_mc ?? r.run_id}
                      </Link>{" "}
                      — <OutcomeBadge outcome={deriveOutcome(r)} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        );
      })}
    </main>
  );
}
