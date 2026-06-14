import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import {
  requireSession,
  activeOrg,
  assertOrgAccess,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";
import { createOrder, appendOrderEvent } from "@/lib/orders";
import { runIntakeTurn, type Extracted, type IntakeMessage } from "@/lib/intake";

// POST /api/intake { orderId?, message }
// Runs one chat-intake assistant turn. Creates a DRAFT Order(intakeChannel:CHAT)
// on the first message; refines it on later messages. Persists every turn as a
// ChatMessage. Returns { orderId, reply, extracted, ready }.
export async function POST(req: NextRequest) {
  try {
    const session = await requireSession();
    const membership = await activeOrg(session);
    if (!membership) {
      return NextResponse.json({ error: "No active organization" }, { status: 400 });
    }

    const body = (await req.json().catch(() => ({}))) as {
      orderId?: string;
      message?: string;
    };
    const message = String(body.message ?? "").trim();
    if (!message) {
      return NextResponse.json({ error: "message is required" }, { status: 400 });
    }

    // Resolve / create the order this turn belongs to.
    let orderId = body.orderId ?? null;
    let history: IntakeMessage[] = [];
    let priorExtracted: Partial<Extracted> = {};
    let isNew = false;

    if (orderId) {
      const order = await prisma.order.findUnique({
        where: { id: orderId },
        include: { messages: { orderBy: { createdAt: "asc" } } },
      });
      if (!order) {
        return NextResponse.json({ error: "Order not found" }, { status: 404 });
      }
      try {
        await assertOrgAccess(order.orgId);
      } catch {
        return NextResponse.json({ error: "Order not found" }, { status: 404 });
      }
      history = order.messages.map((m) => ({
        role: m.role as IntakeMessage["role"],
        content: m.content,
      }));
      priorExtracted = {
        title: order.title && order.title !== "Untitled request" ? order.title : null,
        category: order.category,
        brand: order.brand,
        maxBudgetCents: order.maxBudgetCents,
      };
    } else {
      // First message → create a DRAFT order so the transcript has a home.
      isNew = true;
      const order = await createOrder({
        orgId: membership.orgId,
        requestedById: session.user.id,
        title: deriveTitleSeed(message),
        intakeChannel: "CHAT",
      });
      orderId = order.id;
    }

    // Run the assistant turn (robust: falls back if OpenAI errors / no key).
    const turn = await runIntakeTurn(history, message, priorExtracted);

    // Persist user + assistant turns.
    await prisma.chatMessage.createMany({
      data: [
        { orderId: orderId!, role: "user", content: message },
        { orderId: orderId!, role: "assistant", content: turn.reply },
      ],
    });

    // Refine the order with the cumulative extraction.
    const ex = turn.extracted;
    await prisma.order.update({
      where: { id: orderId! },
      data: {
        ...(ex.title ? { title: ex.title } : {}),
        ...(ex.category !== undefined ? { category: ex.category } : {}),
        ...(ex.brand !== undefined ? { brand: ex.brand } : {}),
        ...(ex.maxBudgetCents !== undefined
          ? { maxBudgetCents: ex.maxBudgetCents }
          : {}),
      },
    });

    if (!isNew) {
      await appendOrderEvent({
        orderId: orderId!,
        orgId: membership.orgId,
        type: "message",
        actorType: "user",
        actorUserId: session.user.id,
        message: "Refined the request via chat",
      }).catch(() => {});
    }

    return NextResponse.json({
      orderId,
      reply: turn.reply,
      extracted: turn.extracted,
      ready: turn.ready,
    });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}

function deriveTitleSeed(message: string): string {
  const firstLine = message.split(/[\n.!?]/)[0].trim() || message;
  return firstLine.length > 80 ? firstLine.slice(0, 77) + "…" : firstLine;
}
