import { NextResponse } from "next/server";
import {
  requireSession,
  activeOrg,
  assertCanManage,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";

// POST /api/router/retrain — the admin "Retrain now" button. Auto-retrain proper
// runs on the Railway cron host (pioneer.auto_retrain.run); a manual trigger asks
// that host to run NOW. We forward to RETRAIN_TRIGGER_URL (the cron service's HTTP
// entry) with the internal token if configured. If it isn't wired, we return a
// clear, non-error payload telling the admin to run it manually — the loop still
// runs on its daily schedule regardless.
//
// OWNER/ADMIN only (gated on the caller's active-org RBAC, since RouterConfig is
// global).
export async function POST() {
  try {
    const session = await requireSession();
    const active = await activeOrg(session);
    if (!active) throw new ForbiddenError("No active organization");
    await assertCanManage(active.orgId);

    const triggerUrl = process.env.RETRAIN_TRIGGER_URL;
    if (!triggerUrl) {
      return NextResponse.json({
        triggered: false,
        message:
          "RETRAIN_TRIGGER_URL not configured. The daily cron still runs on schedule; " +
          "to retrain now run `python retrain_cron/run.py` (or trigger the Railway cron service manually).",
      });
    }

    try {
      const res = await fetch(`${triggerUrl.replace(/\/$/, "")}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-internal-token": process.env.INTERNAL_API_TOKEN ?? "",
        },
        body: JSON.stringify({ trigger: "manual" }),
        signal: AbortSignal.timeout(10000),
      });
      const ok = res.ok;
      const detail = await res.text().catch(() => "");
      return NextResponse.json({
        triggered: ok,
        status: res.status,
        message: ok
          ? "Retrain triggered on the cron host. Watch the run history for the result."
          : `Trigger host returned ${res.status}: ${detail.slice(0, 200)}`,
      });
    } catch (err) {
      return NextResponse.json(
        {
          triggered: false,
          message: `Failed to reach RETRAIN_TRIGGER_URL: ${(err as Error).message}`,
        },
        { status: 502 },
      );
    }
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
