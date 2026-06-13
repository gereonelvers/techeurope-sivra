// Shared domain types used across pages, API routes, seed and reward logic.

export const SITES = ["site-a", "site-b", "site-c"] as const;
export type Site = (typeof SITES)[number];

export const CATEGORIES = [
  "Bikes",
  "Laptops",
  "Phones",
  "Cameras",
  "Furniture",
  "Audio",
] as const;
export type Category = (typeof CATEGORIES)[number];

export const CONDITIONS = ["New", "Like New", "Good", "Fair"] as const;
export type Condition = (typeof CONDITIONS)[number];

// Ordering from best to worst. Lower index == better condition.
export const CONDITION_RANK: Record<string, number> = {
  New: 0,
  "Like New": 1,
  Good: 2,
  Fair: 3,
};

export const CITIES = [
  "München",
  "Berlin",
  "Hamburg",
  "Köln",
  "Frankfurt",
] as const;
export type City = (typeof CITIES)[number];

export function isSite(value: string): value is Site {
  return (SITES as readonly string[]).includes(value);
}

// The agent's goal. The CHEAPEST matching listing on that site is the unique
// target. minCondition means "at least this good" (rank <= rank(minCondition)).
export interface TaskSpec {
  category?: Category | string;
  brand?: string;
  maxPriceCents?: number;
  minCondition?: Condition | string;
  city?: string;
}

export interface TargetAttrs {
  category: string;
  brand: string;
  condition: string;
  priceCents: number;
  city: string;
}

// Event types fired on buyer actions. These are also the reward checkpoints,
// listed in the canonical funnel order.
export const CHECKPOINT_ORDER = [
  "SEARCH_SUBMITTED",
  "FILTER_APPLIED",
  "PRODUCT_VIEWED",
  "ADD_TO_CART",
  "CHECKOUT_STARTED",
  "ORDER_PLACED",
] as const;
export type EventType = (typeof CHECKPOINT_ORDER)[number];

export interface RewardResult {
  success: boolean;
  attrMatch: number; // 0..1
  checkpointsHit: number;
  checkpointsTotal: number;
  steps: number;
  scalar: number;
}
