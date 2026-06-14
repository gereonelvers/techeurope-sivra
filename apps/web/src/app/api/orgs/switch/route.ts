import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  assertOrgAccess,
  ORG_COOKIE,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";

// POST /api/orgs/switch { orgId } — set the active org cookie after verifying
// the signed-in user is actually a member of that org.
export async function POST(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as { orgId?: string };
    const orgId = String(body.orgId ?? "").trim();
    if (!orgId) {
      return NextResponse.json({ error: "orgId is required" }, { status: 400 });
    }

    // Membership check — only switch into orgs you belong to.
    await assertOrgAccess(orgId);

    const res = NextResponse.json({ ok: true, orgId });
    res.cookies.set(ORG_COOKIE, orgId, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 365,
    });
    return res;
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
