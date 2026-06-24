import Link from "next/link";
import { notFound } from "next/navigation";
import { requireAppUser } from "@/lib/auth";
import { getCallOutcome } from "@/lib/calls";
import { deriveCeilingRespected, deriveOutcome, usd, duration, signedPct, spreadBucket } from "@/lib/kpis";
import { OutcomeBadge, BoolBadge, AuthorityBadge, TopNav } from "@/components/ui";
import "../../dash.css";

export const dynamic = "force-dynamic";

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="field-label">{label}</div>
      <div className="field-value">{value ?? "—"}</div>
    </div>
  );
}

export default async function CallDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  await requireAppUser();
  const { runId } = await params;

  const r = await getCallOutcome(runId);
  if (!r) notFound();

  const spread =
    r.agreed_rate != null && r.posted_rate
      ? ((r.agreed_rate - r.posted_rate) / r.posted_rate) * 100
      : null;

  return (
    <main className="dash">
      <TopNav active="calls" />
      <Link href="/calls" className="back-link">← Recent Calls</Link>
      <h1 className="with-badge">
        Call detail <OutcomeBadge outcome={deriveOutcome(r)} />
      </h1>
      <p className="muted">
        run <code>{r.run_id}</code> · {r.completed_at ?? "—"}
      </p>

      <h2>Carrier &amp; identity</h2>
      <div className="panel detail-grid">
        <Field label="MC number" value={r.carrier_mc} />
        <Field label="Carrier name" value={r.carrier_name} />
        <Field label="Registered phone (masked)" value={r.carrier_phone} />
        <Field label="FMCSA authority" value={<AuthorityBadge status={r.authority_status} />} />
        <Field label="OTP verified" value={<BoolBadge value={r.otp_verified} />} />
        <Field label="OTP attempts" value={r.otp_attempts} />
      </div>

      <h2>Load &amp; lane</h2>
      <div className="panel detail-grid">
        <Field label="Lane" value={r.lane} />
        <Field label="Origin → Dest" value={`${r.origin_state ?? "—"} → ${r.dest_state ?? "—"}`} />
        <Field label="Equipment" value={r.equipment} />
        <Field label="Load ID" value={r.load_id} />
      </div>

      <h2>Negotiation &amp; booking</h2>
      <div className="panel detail-grid">
        <Field label="Posted rate" value={usd(r.posted_rate)} />
        <Field label="Agreed rate" value={usd(r.agreed_rate)} />
        <Field
          label="Agreed vs posted"
          value={spread != null ? `${signedPct(spread)} (${spreadBucket(spread)})` : "—"}
        />
        <Field label="Negotiation rounds" value={r.negotiation_rounds} />
        <Field
          label="Ceiling respected"
          value={<BoolBadge value={deriveCeilingRespected(r)} trueLabel="ok" falseLabel="BREACH" />}
        />
        <Field label="Booking ref" value={r.booking_ref} />
        <Field label="Handoff mocked" value={<BoolBadge value={r.handoff_mocked} />} />
      </div>

      {/* This view shows agreed-vs-POSTED only — never agreed-vs-ceiling and never a
          raw margin/ceiling. That signal isn't in the data layer at all. */}

      <h2>Run &amp; reliability</h2>
      <div className="panel detail-grid">
        <Field label="Outcome" value={<OutcomeBadge outcome={deriveOutcome(r)} />} />
        <Field label="Decline reason" value={r.decline_reason} />
        <Field label="Handle time" value={duration(r.handle_time_s)} />
        <Field label="TMS fault" value={r.tms_fault_observed ?? "none"} />
        <Field
          label="Transcript"
          value={r.transcript_url ? <a className="back-link" href={r.transcript_url} target="_blank" rel="noreferrer">open ↗</a> : "—"}
        />
        <Field
          label="Recording"
          value={r.recording_url ? <a className="back-link" href={r.recording_url} target="_blank" rel="noreferrer">open ↗</a> : "—"}
        />
      </div>

      {r.notes ? (
        <>
          <h2>Notes</h2>
          <div className="panel">{r.notes}</div>
        </>
      ) : null}
    </main>
  );
}
