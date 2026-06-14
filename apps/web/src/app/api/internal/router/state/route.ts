import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import { getRouterState } from "@/lib/router_config";

// GET /api/internal/router/state — the auto-retrain cron's read: the active model
// + resolved-feedback count since the last train (vs minSamples threshold) + the
// auto-retrain knobs. Guarded by x-internal-token.
export async function GET(req: NextRequest) {
  try {
    assertInternal(req);
  } catch (err) {
    if (err instanceof InternalAuthError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }

  const state = await getRouterState();
  return NextResponse.json(state);
}
