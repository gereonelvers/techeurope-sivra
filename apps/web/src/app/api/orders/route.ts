import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import {
  requireSession,
  activeOrg,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";
import { createOrder } from "@/lib/orders";

// POST /api/orders — create a DRAFT Order in the caller's active org.
// Body: { title, description?, category?, brand?, maxBudgetCents?, intakeChannel? }
export async function POST(req: NextRequest) {
  try {
    const session = await requireSession();
    const membership = await activeOrg(session);
    if (!membership) {
      return NextResponse.json({ error: "No active organization" }, { status: 400 });
    }

    const body = (await req.json().catch(() => ({}))) as {
      title?: string;
      description?: string;
      category?: string;
      brand?: string;
      maxBudgetCents?: number;
      intakeChannel?: string;
    };
    const title = String(body.title ?? "").trim();
    if (!title) {
      return NextResponse.json({ error: "title is required" }, { status: 400 });
    }

    const intakeChannel =
      body.intakeChannel === "VOICE" || body.intakeChannel === "API"
        ? body.intakeChannel
        : "CHAT";

    const order = await createOrder({
      orgId: membership.orgId,
      requestedById: session.user.id,
      title,
      description: body.description ?? null,
      category: body.category ?? null,
      brand: body.brand ?? null,
      maxBudgetCents:
        typeof body.maxBudgetCents === "number" ? body.maxBudgetCents : null,
      intakeChannel,
    });

    return NextResponse.json({ order }, { status: 201 });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}

// GET /api/orders — list this org's orders, newest first.
export async function GET() {
  try {
    const session = await requireSession();
    const membership = await activeOrg(session);
    if (!membership) {
      return NextResponse.json({ orders: [] });
    }
    const orders = await prisma.order.findMany({
      where: { orgId: membership.orgId },
      orderBy: { createdAt: "desc" },
      select: {
        id: true,
        title: true,
        category: true,
        brand: true,
        maxBudgetCents: true,
        currency: true,
        status: true,
        intakeChannel: true,
        resultTitle: true,
        resultPriceCents: true,
        createdAt: true,
        updatedAt: true,
      },
    });
    return NextResponse.json({ orders });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
