import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { assertCanManage, UnauthorizedError, ForbiddenError } from "@/lib/org";
import { PURCHASING_ROLES } from "@/lib/policy";

const ORG_ROLES = ["OWNER", "ADMIN", "MEMBER"] as const;

// PATCH /api/members/:id — change a member's role / purchasingRole /
// approvalLimit. OWNER/ADMIN only (org derived from the membership itself).
export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    const target = await prisma.membership.findUnique({
      where: { id: params.id },
      select: { id: true, orgId: true, userId: true, role: true },
    });
    if (!target) {
      return NextResponse.json({ error: "Member not found" }, { status: 404 });
    }

    // RBAC: must be OWNER/ADMIN of the target's org.
    await assertCanManage(target.orgId);

    const body = (await req.json().catch(() => ({}))) as {
      role?: string;
      purchasingRole?: string | null;
      approvalLimitCents?: number | null;
    };

    const data: {
      role?: (typeof ORG_ROLES)[number];
      purchasingRole?: string | null;
      approvalLimitCents?: number | null;
    } = {};

    if (body.role !== undefined) {
      if (!(ORG_ROLES as readonly string[]).includes(body.role)) {
        return NextResponse.json({ error: "Invalid role" }, { status: 400 });
      }
      // Guard: don't let the last OWNER be demoted (org would be unmanageable).
      if (target.role === "OWNER" && body.role !== "OWNER") {
        const ownerCount = await prisma.membership.count({
          where: { orgId: target.orgId, role: "OWNER" },
        });
        if (ownerCount <= 1) {
          return NextResponse.json(
            { error: "Cannot demote the last owner" },
            { status: 400 },
          );
        }
      }
      data.role = body.role as (typeof ORG_ROLES)[number];
    }

    if (body.purchasingRole !== undefined) {
      const pr = body.purchasingRole;
      if (pr !== null && !(PURCHASING_ROLES as readonly string[]).includes(pr)) {
        return NextResponse.json(
          { error: "Invalid purchasingRole" },
          { status: 400 },
        );
      }
      data.purchasingRole = pr;
    }

    if (body.approvalLimitCents !== undefined) {
      const lim = body.approvalLimitCents;
      data.approvalLimitCents =
        lim === null ? null : Math.max(0, Math.round(Number(lim)));
    }

    const updated = await prisma.membership.update({
      where: { id: target.id },
      data,
      include: {
        user: { select: { email: true, name: true } },
      },
    });
    return NextResponse.json({ member: updated });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}

// DELETE /api/members/:id — remove a member from the org. OWNER/ADMIN only.
export async function DELETE(
  _req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    const target = await prisma.membership.findUnique({
      where: { id: params.id },
      select: { id: true, orgId: true, role: true },
    });
    if (!target) {
      return NextResponse.json({ error: "Member not found" }, { status: 404 });
    }

    await assertCanManage(target.orgId); // RBAC

    // Never remove the last owner.
    if (target.role === "OWNER") {
      const ownerCount = await prisma.membership.count({
        where: { orgId: target.orgId, role: "OWNER" },
      });
      if (ownerCount <= 1) {
        return NextResponse.json(
          { error: "Cannot remove the last owner" },
          { status: 400 },
        );
      }
    }

    await prisma.membership.delete({ where: { id: target.id } });
    return NextResponse.json({ ok: true });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
