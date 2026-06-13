import { fromJson } from "./json";
import {
  CHECKPOINT_ORDER,
  RewardResult,
  TargetAttrs,
} from "./types";

// A minimal, storage-agnostic view of an episode + its event stream. The API
// route and the smoke test both build one of these and call computeReward, so
// the reward oracle has exactly one implementation.
export interface EpisodeForReward {
  id: string;
  targetItemId: number | null;
  // Stored as JSON string (TEXT column) or already-parsed object.
  targetAttrs: string | TargetAttrs | null;
}

export interface EventForReward {
  type: string;
  // Stored as JSON string (TEXT column) or already-parsed object.
  payload: string | Record<string, unknown> | null;
  step?: number;
}

function parsePayload(
  payload: EventForReward["payload"],
): Record<string, unknown> {
  if (payload == null) return {};
  if (typeof payload === "string") {
    return fromJson<Record<string, unknown>>(payload) ?? {};
  }
  return payload;
}

function parseTargetAttrs(
  attrs: EpisodeForReward["targetAttrs"],
): TargetAttrs | null {
  if (attrs == null) return null;
  if (typeof attrs === "string") return fromJson<TargetAttrs>(attrs);
  return attrs;
}

// Weighting of the scalar reward. success dominates, attrMatch and funnel
// progress provide dense, partial-credit signal.
const W_SUCCESS = 0.6;
const W_ATTR = 0.25;
const W_CHECKPOINTS = 0.15;

const PRICE_TOLERANCE = 0.0; // ordered price must be <= target price (cheapest)

/**
 * Replay an episode's events and produce a structured reward. Pure function:
 * no DB access, no globals — the same logic powers the /api/reward oracle and
 * the smoke test.
 */
export function computeReward(
  episode: EpisodeForReward,
  events: EventForReward[],
): RewardResult {
  const checkpointsTotal = CHECKPOINT_ORDER.length;

  // Distinct milestone event types reached.
  const seenTypes = new Set<string>();
  for (const e of events) {
    if ((CHECKPOINT_ORDER as readonly string[]).includes(e.type)) {
      seenTypes.add(e.type);
    }
  }
  const checkpointsHit = seenTypes.size;

  // success = an ORDER_PLACED event whose itemId === episode.targetItemId.
  const orderEvents = events.filter((e) => e.type === "ORDER_PLACED");
  let success = false;
  let orderedAttrs: TargetAttrs | null = null;
  let orderedItemId: number | null = null;

  const target = parseTargetAttrs(episode.targetAttrs);

  for (const order of orderEvents) {
    const payload = parsePayload(order.payload);
    const itemId =
      typeof payload.itemId === "number"
        ? payload.itemId
        : Number(payload.itemId);
    if (
      episode.targetItemId != null &&
      Number.isFinite(itemId) &&
      itemId === episode.targetItemId
    ) {
      success = true;
    }
    // Capture the attrs of the LAST order for attrMatch scoring.
    orderedItemId = Number.isFinite(itemId) ? itemId : orderedItemId;
    if (payload.attrs && typeof payload.attrs === "object") {
      orderedAttrs = payload.attrs as TargetAttrs;
    } else if (typeof payload.priceCents === "number") {
      // Fall back to a partial attrs object built from the payload.
      orderedAttrs = {
        category: (payload.category as string) ?? "",
        brand: (payload.brand as string) ?? "",
        condition: (payload.condition as string) ?? "",
        priceCents: payload.priceCents as number,
        city: (payload.city as string) ?? "",
      };
    }
  }

  // attrMatch: compare ordered item attrs vs targetAttrs. 3 equally-weighted
  // checks: category match, brand match, price within target.
  let attrMatch = 0;
  if (target && orderedAttrs) {
    let score = 0;
    const parts = 3;
    if (orderedAttrs.category === target.category) score += 1;
    if (orderedAttrs.brand === target.brand) score += 1;
    if (
      typeof orderedAttrs.priceCents === "number" &&
      orderedAttrs.priceCents <= target.priceCents * (1 + PRICE_TOLERANCE)
    ) {
      score += 1;
    }
    attrMatch = score / parts;
  } else if (success) {
    // Ordered the exact target but no attrs in payload — treat as full match.
    attrMatch = 1;
  }

  const checkpointFraction = checkpointsHit / checkpointsTotal;

  const scalar =
    W_SUCCESS * (success ? 1 : 0) +
    W_ATTR * attrMatch +
    W_CHECKPOINTS * checkpointFraction;

  return {
    success,
    attrMatch,
    checkpointsHit,
    checkpointsTotal,
    steps: events.length,
    scalar: Number(scalar.toFixed(4)),
  };
}
