import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  requireSession,
  activeOrg,
  assertCanManage,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";
import { updateRouterConfig, getRouterConfig } from "@/lib/router_config";

// Admin (session-authed, OWNER/ADMIN) management of the GLOBAL RouterConfig knobs.
// RouterConfig is platform-wide, but only an OWNER/ADMIN of some org may touch it,
// so we gate on the caller's active-org RBAC.
async function assertAdmin(): Promise<void> {
  const session = await requireSession();
  const active = await activeOrg(session);
  if (!active) throw new ForbiddenError("No active organization");
  await assertCanManage(active.orgId); // OWNER/ADMIN of the active org
}

// GET /api/router/config — the current RouterConfig (for the admin page client).
export async function GET() {
  try {
    await assertAdmin();
    const cfg = await getRouterConfig();
    return NextResponse.json({ config: cfg });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}

// PATCH /api/router/config { autoRetrainEnabled?, minSamples? } — toggle
// auto-retrain + edit the sample threshold.
export async function PATCH(req: NextRequest) {
  try {
    await assertAdmin();
    const body = (await req.json().catch(() => ({}))) as {
      autoRetrainEnabled?: boolean;
      minSamples?: number;
    };
    const patch: { autoRetrainEnabled?: boolean; minSamples?: number } = {};
    if (typeof body.autoRetrainEnabled === "boolean")
      patch.autoRetrainEnabled = body.autoRetrainEnabled;
    if (body.minSamples !== undefined && Number.isFinite(Number(body.minSamples)))
      patch.minSamples = Number(body.minSamples);
    const cfg = await updateRouterConfig(patch);
    return NextResponse.json({ config: cfg });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
