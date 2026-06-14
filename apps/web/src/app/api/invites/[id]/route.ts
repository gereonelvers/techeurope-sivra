import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { assertCanManage, UnauthorizedError, ForbiddenError } from "@/lib/org";

// DELETE /api/invites/:id — revoke a pending invite. OWNER/ADMIN only.
export async function DELETE(
  _req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    const invite = await prisma.invite.findUnique({
      where: { id: params.id },
      select: { id: true, orgId: true },
    });
    if (!invite) {
      return NextResponse.json({ error: "Invite not found" }, { status: 404 });
    }

    await assertCanManage(invite.orgId); // RBAC

    await prisma.invite.delete({ where: { id: invite.id } });
    return NextResponse.json({ ok: true });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
