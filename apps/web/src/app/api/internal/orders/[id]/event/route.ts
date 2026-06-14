import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import { appendOrderEvent } from "@/lib/orders";
import type { Prisma } from "@prisma/client";

// POST /api/internal/orders/:id/event { type, actorType, message?, data? }
// Best-effort audit / mission update from the Python fleet. Guarded by
// x-internal-token. Appends an append-only OrderEvent.
export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    assertInternal(req);
  } catch (err) {
    if (err instanceof InternalAuthError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }

  const order = await prisma.order.findUnique({
    where: { id: params.id },
    select: { id: true, orgId: true },
  });
  if (!order) {
    return NextResponse.json({ error: "Order not found" }, { status: 404 });
  }

  const body = (await req.json().catch(() => ({}))) as {
    type?: string;
    actorType?: string;
    message?: string;
    data?: Prisma.InputJsonValue;
  };
  const type = String(body.type ?? "").trim();
  if (!type) {
    return NextResponse.json({ error: "type is required" }, { status: 400 });
  }
  const actorType = String(body.actorType ?? "agent").trim() || "agent";

  const event = await appendOrderEvent({
    orderId: order.id,
    orgId: order.orgId,
    type,
    actorType,
    message: body.message ?? null,
    data: body.data ?? null,
  });

  return NextResponse.json({ event: { id: event.id } }, { status: 201 });
}
