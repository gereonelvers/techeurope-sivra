import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import {
  requireSession,
  assertOrgAccess,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";

// GET /api/orders/:id — full order detail (events + escalations + messages),
// org-scoped. 404 if the order is missing OR belongs to another org (no leak).
export async function GET(
  _req: Request,
  { params }: { params: { id: string } },
) {
  try {
    await requireSession();

    const order = await prisma.order.findUnique({
      where: { id: params.id },
      include: {
        events: { orderBy: { createdAt: "asc" } },
        escalations: { orderBy: { createdAt: "asc" } },
        messages: { orderBy: { createdAt: "asc" } },
      },
    });
    if (!order) {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }
    // Cross-org access → 404 (don't reveal existence).
    try {
      await assertOrgAccess(order.orgId);
    } catch {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }

    return NextResponse.json({ order });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
