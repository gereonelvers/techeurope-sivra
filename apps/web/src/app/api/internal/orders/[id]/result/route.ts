import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import { appendOrderEvent } from "@/lib/orders";
import type { Prisma } from "@prisma/client";

// POST /api/internal/orders/:id/result
//   { resultItemId, resultTitle, resultPriceCents, receipt }
// Marks the order COMPLETED, stores the result + receipt, appends "completed".
// Guarded by x-internal-token.
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
    resultItemId?: number | null;
    resultTitle?: string | null;
    resultPriceCents?: number | null;
    receipt?: Prisma.InputJsonValue;
  };

  const resultPriceCents =
    body.resultPriceCents == null ? null : Math.round(body.resultPriceCents);

  const updated = await prisma.order.update({
    where: { id: order.id },
    data: {
      status: "COMPLETED",
      resultItemId: body.resultItemId ?? null,
      resultTitle: body.resultTitle ?? null,
      resultPriceCents,
      receipt: body.receipt ?? undefined,
      completedAt: new Date(),
    },
    select: { id: true, status: true },
  });

  await appendOrderEvent({
    orderId: order.id,
    orgId: order.orgId,
    type: "completed",
    actorType: "agent",
    message: body.resultTitle
      ? `Purchased: ${body.resultTitle}${
          resultPriceCents != null ? ` (€${(resultPriceCents / 100).toFixed(2)})` : ""
        }`
      : "Order completed",
    data: {
      resultItemId: body.resultItemId ?? null,
      resultPriceCents,
    },
  }).catch(() => {});

  return NextResponse.json({ order: updated });
}
