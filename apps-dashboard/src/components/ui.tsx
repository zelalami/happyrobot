import Link from "next/link";
import type { Outcome } from "@/lib/types";

const NAV = [
  { href: "/", key: "overview", label: "Overview" },
  { href: "/calls", key: "calls", label: "Recent Calls" },
  { href: "/compliance", key: "compliance", label: "Compliance" },
];

export function TopNav({ active }: { active: string }) {
  return (
    <nav className="dash-nav">
      <span className="dash-brand">Carrier Sales · Ops</span>
      <span className="dash-nav-links">
        {NAV.map((n) => (
          <Link key={n.key} href={n.href} className={n.key === active ? "active" : ""}>
            {n.label}
          </Link>
        ))}
      </span>
    </nav>
  );
}

export function KpiCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value${tone ? " " + tone : ""}`}>{value}</div>
      {sub ? <div className="kpi-sub">{sub}</div> : null}
    </div>
  );
}

const OUTCOME_TONE: Record<string, "good" | "bad" | "warn" | "muted"> = {
  booked: "good",
  negotiation_failed: "warn",
  carrier_declined: "warn",
  no_authority: "bad",
  otp_failed: "bad",
  tms_error: "bad",
  no_loads: "muted",
  abandoned: "muted",
  unknown: "muted",
};

export function OutcomeBadge({ outcome }: { outcome: Outcome | string }) {
  const tone = OUTCOME_TONE[outcome] ?? "muted";
  return <span className={`badge ${tone}`}>{outcome.replace(/_/g, " ")}</span>;
}

export function BoolBadge({
  value,
  trueLabel = "yes",
  falseLabel = "no",
}: {
  value: boolean | null;
  trueLabel?: string;
  falseLabel?: string;
}) {
  if (value == null) return <span className="muted">—</span>;
  return value ? (
    <span className="badge good">{trueLabel}</span>
  ) : (
    <span className="badge bad">{falseLabel}</span>
  );
}

export function AuthorityBadge({ status }: { status: string | null }) {
  if (!status) return <span className="muted">—</span>;
  const tone = status === "active" ? "good" : status === "not_found" ? "muted" : "bad";
  return <span className={`badge ${tone}`}>{status}</span>;
}
