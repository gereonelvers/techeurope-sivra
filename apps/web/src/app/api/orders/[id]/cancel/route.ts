import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import {
  requireSession,
  assertOrgAccess,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";
import { appendOrderEvent } from "@/lib/orders";

// POST /api/orders/:id/cancel — flip to CANCELLED + append a "note" audit event.
// Org-scoped; 404 cross-org.
export async function POST(
  _req: Request,
  { params }: { params: { id: string } },
) {
  try {
    const session = await requireSession();
    const order = await prisma.order.findUnique({
      where: { id: params.id },
      select: { id: true, orgId: true, status: true },
    });
    if (!order) {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }
    try {
      await assertOrgAccess(order.orgId);
    } catch {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }

    if (order.status === "COMPLETED" || order.status === "CANCELLED") {
      return NextResponse.json(
        { error: `Order already ${order.status.toLowerCase()}` },
        { status: 409 },
      );
    }

    const updated = await prisma.order.update({
      where: { id: order.id },
      data: { status: "CANCELLED" },
      select: { id: true, status: true },
    });
    await appendOrderEvent({
      orderId: order.id,
      orgId: order.orgId,
      type: "note",
      actorType: "user",
      actorUserId: session.user.id,
      message: "Order cancelled",
    });

    return NextResponse.json({ order: updated });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
