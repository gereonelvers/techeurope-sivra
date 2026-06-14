import { requireSession, activeOrg } from "@/lib/org";
import { prisma } from "@/lib/db";
import { normalizeFleetTier } from "@/lib/fleet-tiers";
import { IntakeChat } from "./IntakeChat";

// New-order chat intake. The assistant (OpenAI) asks 1–2 clarifying questions,
// extracts { title, category?, brand?, maxBudgetCents }, and on confirmation
// creates + launches the Order, then routes to its detail page. The fleet-size
// picker defaults to the org's configured tier (Settings → Browsing fleet).
export default async function NewOrderPage() {
  const session = await requireSession();
  const active = await activeOrg(session);
  const orgRow = active
    ? await prisma.organization.findUnique({
        where: { id: active.orgId },
        select: { defaultFleetTier: true },
      })
    : null;
  const defaultFleetTier = normalizeFleetTier(orgRow?.defaultFleetTier);

  return (
    <div>
      <h1 className="text-3xl font-semibold">New order</h1>
      <p className="mt-2 text-sm leading-relaxed text-ink/60">
        Tell sivra what you need. The more detail, the better the search — but a
        sentence is enough to start.
      </p>
      <IntakeChat defaultFleetTier={defaultFleetTier} />
    </div>
  );
}
