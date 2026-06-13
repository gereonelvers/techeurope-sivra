import { prisma } from "./db";
import { CONDITION_RANK, TargetAttrs, TaskSpec } from "./types";

// Build the Prisma `where` clause that selects every listing on `site` that
// satisfies the task spec. minCondition means "at least this good" (rank <=).
export function buildTaskWhere(site: string, spec: TaskSpec) {
  const where: Record<string, unknown> = { site };

  if (spec.category) where.category = spec.category;
  if (spec.brand) where.brand = spec.brand;
  if (spec.city) where.city = spec.city;
  if (typeof spec.maxPriceCents === "number") {
    where.priceCents = { lte: spec.maxPriceCents };
  }
  if (spec.minCondition && spec.minCondition in CONDITION_RANK) {
    const maxRank = CONDITION_RANK[spec.minCondition];
    const allowed = Object.entries(CONDITION_RANK)
      .filter(([, rank]) => rank <= maxRank)
      .map(([condition]) => condition);
    where.condition = { in: allowed };
  }

  return where;
}

export interface ComputedTarget {
  targetItemId: number | null;
  targetAttrs: TargetAttrs | null;
}

// The ground-truth target for an episode: the CHEAPEST matching listing on the
// site (ties broken by lowest id so it is deterministic and unique).
export async function computeTarget(
  site: string,
  spec: TaskSpec,
): Promise<ComputedTarget> {
  const where = buildTaskWhere(site, spec);

  const target = await prisma.listing.findFirst({
    where,
    orderBy: [{ priceCents: "asc" }, { id: "asc" }],
  });

  if (!target) return { targetItemId: null, targetAttrs: null };

  return {
    targetItemId: target.id,
    targetAttrs: {
      category: target.category,
      brand: target.brand,
      condition: target.condition,
      priceCents: target.priceCents,
      city: target.city,
    },
  };
}
