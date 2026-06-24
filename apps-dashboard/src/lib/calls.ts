import { getTwinRows } from "@/lib/twin";
import type { CallOutcome } from "@/lib/types";

// Thin wrapper over the template's Twin client (gateway + hr_token cookie + x-org-id).
// PostgREST query params: ?order=completed_at.desc&limit=N, and run_id=eq.<uuid> for one row.

const TABLE = "call_outcomes";

export async function getCallOutcomes(limit = 500): Promise<CallOutcome[]> {
  const capped = Math.min(Math.max(limit, 1), 500);
  const rows = await getTwinRows<CallOutcome[]>(TABLE, {
    params: { order: "completed_at.desc", limit: String(capped) },
  });
  return Array.isArray(rows) ? rows : [];
}

export async function getCallOutcome(runId: string): Promise<CallOutcome | null> {
  const rows = await getTwinRows<CallOutcome[]>(TABLE, {
    params: { run_id: `eq.${runId}`, limit: "1" },
  });
  return Array.isArray(rows) && rows.length ? rows[0] : null;
}
