// Browsing-fleet size tiers. A "search" dispatches a fleet of N buyer agents;
// the tier picks N. The org sets a default (Settings → Browsing fleet) and each
// order may override it (intake aside / order detail). The resolved tier is
// persisted on the Order and its agent count flows to the orchestrator (and is
// echoed on Order.nAgents). Keep this file the SINGLE source of truth for the
// tier → agent-count mapping; the fleet runner caps at its own FLEET_MAX_N.

export type FleetTier = "SMALL" | "MEDIUM" | "DEEP";

export const FLEET_TIERS: Record<
  FleetTier,
  { label: string; n: number; blurb: string }
> = {
  SMALL: { label: "Small", n: 3, blurb: "3 agents · a quick scan" },
  MEDIUM: { label: "Medium", n: 12, blurb: "12 agents · balanced" },
  DEEP: { label: "Deep", n: 100, blurb: "100 agents · exhaustive sweep" },
};

// Display order for pickers.
export const FLEET_TIER_ORDER: FleetTier[] = ["SMALL", "MEDIUM", "DEEP"];

export const DEFAULT_FLEET_TIER: FleetTier = "MEDIUM";

export function isFleetTier(v: unknown): v is FleetTier {
  return v === "SMALL" || v === "MEDIUM" || v === "DEEP";
}

/** Coerce any input to a valid tier, falling back to the default (MEDIUM). */
export function normalizeFleetTier(v?: string | null): FleetTier {
  const up = (v ?? "").toUpperCase();
  return isFleetTier(up) ? up : DEFAULT_FLEET_TIER;
}

/**
 * Effective tier for a launch: an explicit per-order tier wins; otherwise fall
 * back to the org default; otherwise MEDIUM.
 */
export function resolveFleetTier(
  orderTier?: string | null,
  orgDefault?: string | null,
): FleetTier {
  const ot = (orderTier ?? "").toUpperCase();
  if (isFleetTier(ot)) return ot;
  return normalizeFleetTier(orgDefault);
}

/** Agent count for a tier (defaults applied). */
export function fleetTierToN(tier?: string | null): number {
  return FLEET_TIERS[normalizeFleetTier(tier)].n;
}

/** Short "Medium · 12 agents" label for read-only display. */
export function fleetTierLabel(tier?: string | null): string {
  const t = normalizeFleetTier(tier);
  return `${FLEET_TIERS[t].label} · ${FLEET_TIERS[t].n} agents`;
}
