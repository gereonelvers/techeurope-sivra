import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import {
  requireSession,
  assertOrgAccess,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";

// POST /api/orders/:id/messages { role?, content } — append a ChatMessage to an
// order's transcript. Org-scoped; 404 cross-org. (Intake normally writes these,
// but this lets the UI post a raw message without an assistant turn.)
export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    await requireSession();
    const order = await prisma.order.findUnique({
      where: { id: params.id },
      select: { id: true, orgId: true },
    });
    if (!order) {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }
    try {
      await assertOrgAccess(order.orgId);
    } catch {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }

    const body = (await req.json().catch(() => ({}))) as {
      role?: string;
      content?: string;
    };
    const content = String(body.content ?? "").trim();
    if (!content) {
      return NextResponse.json({ error: "content is required" }, { status: 400 });
    }
    const role =
      body.role === "assistant" || body.role === "system" ? body.role : "user";

    const msg = await prisma.chatMessage.create({
      data: { orderId: order.id, role, content },
    });
    return NextResponse.json({ message: msg }, { status: 201 });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
