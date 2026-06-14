import { prisma } from "@/lib/db";
import { requireSession, activeOrg } from "@/lib/org";
import { OrdersHub, type HubOrder } from "./OrdersHub";

// Orders — the single operational hub. Server-renders this org's orders (newest
// first) and hands them to the OrdersHub client component, which polls the live
// fleet feed and surfaces buyer-agent activity inline (live-only; the recorded
// Mission Control replay is never shown here as if it were live).
export const dynamic = "force-dynamic";

export default async function OrdersPage() {
  const session = await requireSession();
  const membership = await activeOrg(session);

  const rows = membership
    ? await prisma.order.findMany({
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
          resultTitle: true,
          resultPriceCents: true,
          createdAt: true,
          requestedBy: { select: { name: true, email: true } },
        },
      })
    : [];

  const orders: HubOrder[] = rows.map((o) => ({
    id: o.id,
    title: o.title,
    category: o.category,
    brand: o.brand,
    maxBudgetCents: o.maxBudgetCents,
    currency: o.currency,
    status: o.status,
    resultTitle: o.resultTitle,
    resultPriceCents: o.resultPriceCents,
    createdAt: o.createdAt.toISOString(),
    requester: o.requestedBy?.name ?? o.requestedBy?.email ?? null,
  }));

  return <OrdersHub orders={orders} />;
}
