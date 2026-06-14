import { notFound } from "next/navigation";
import { prisma } from "@/lib/db";
import { requireSession, assertOrgAccess, canManageOrg } from "@/lib/org";
import { normalizeFleetTier } from "@/lib/fleet-tiers";
import { OrderDetail } from "./OrderDetail";

// Order detail — status, fields, receipt, and the audit timeline (OrderEvents +
// Escalations merged chronologically). Polls live. Shows an inline approver for
// PENDING escalations the viewer may act on. The heavy lifting (polling, merge,
// approve control) is in the client OrderDetail component.
export const dynamic = "force-dynamic";

export default async function OrderDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const session = await requireSession();

  const order = await prisma.order.findUnique({
    where: { id: params.id },
    select: {
      id: true,
      orgId: true,
      org: { select: { defaultFleetTier: true } },
    },
  });
  if (!order) notFound();

  let membership;
  try {
    membership = await assertOrgAccess(order.orgId);
  } catch {
    notFound();
  }

  // Whether this viewer may resolve escalations: OWNER/ADMIN, or the member the
  // escalation is targeted at. We pass the viewer's membershipId + manage right;
  // the client cross-checks against each PENDING escalation's targetMembershipId.
  const canResolveAny = canManageOrg(membership!.role);

  return (
    <OrderDetail
      orderId={params.id}
      viewerMembershipId={membership!.id}
      viewerCanManage={canResolveAny}
      orgDefaultFleetTier={normalizeFleetTier(order.org?.defaultFleetTier)}
    />
  );
}
