import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  requireSession,
  createOrgForUser,
  ORG_COOKIE,
  UnauthorizedError,
} from "@/lib/org";

// POST /api/orgs — create an Organization owned by the signed-in user.
// Bundles Org + OWNER Membership(purchasingRole=manager) + default
// PermissionPolicy, then makes the new org the user's active org (cookie).
export async function POST(req: NextRequest) {
  try {
    const session = await requireSession();
    const body = (await req.json().catch(() => ({}))) as { name?: string };
    const name = String(body.name ?? "").trim();
    if (!name) {
      return NextResponse.json({ error: "name is required" }, { status: 400 });
    }

    const org = await createOrgForUser(session.user.id, name);

    const res = NextResponse.json({ org }, { status: 201 });
    res.cookies.set(ORG_COOKIE, org.id, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 365,
    });
    return res;
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
