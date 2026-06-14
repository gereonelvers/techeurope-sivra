import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import {
  requireSession,
  assertOrgAccess,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";
import { launchOrder } from "@/lib/orders";

// POST /api/orders/:id/launch — flip DRAFT → SEARCHING, append search_started,
// best-effort kick the orchestrator (only if ORCHESTRATOR_URL set; never fails
// the request if it's unset/unreachable). Org-scoped; 404 cross-org.
// Optional body { fleetTier?: "SMALL"|"MEDIUM"|"DEEP" } overrides the fleet size
// for this search; otherwise the order's stored tier / org default is used.
export async function POST(
  req: Request,
  { params }: { params: { id: string } },
) {
  try {
    await requireSession();
    const body = (await req.json().catch(() => ({}))) as { fleetTier?: string };
    const fleetTier = body?.fleetTier ?? null;
    const order = await prisma.order.findUnique({
      where: { id: params.id },
      select: {
        id: true,
        orgId: true,
        title: true,
        description: true,
        status: true,
        maxBudgetCents: true,
        researchRound: true,
      },
    });
    if (!order) {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }
    try {
      await assertOrgAccess(order.orgId);
    } catch {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }

    if (
      order.status === "CANCELLED" ||
      order.status === "COMPLETED" ||
      order.status === "DECLINED"
    ) {
      return NextResponse.json(
        { error: `Cannot launch an order in status ${order.status}` },
        { status: 409 },
      );
    }

    const updated = await launchOrder(order, { fleetTier });
    return NextResponse.json({ order: { id: updated.id, status: updated.status } });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
