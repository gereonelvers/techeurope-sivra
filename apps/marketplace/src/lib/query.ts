import { CATEGORIES, CONDITIONS } from "./types";

// Next.js page searchParams shape.
export type SearchParams = { [key: string]: string | string[] | undefined };

export interface ParsedFilters {
  q: string;
  categories: string[];
  brands: string[];
  conditions: string[];
  minPrice: number | null; // euros
  maxPrice: number | null; // euros
  location: string;
  sort: "relevance" | "price_asc" | "price_desc" | "rating_desc" | "newest";
  page: number;
  pageSize: number;
}

function asArray(value: string | string[] | undefined): string[] {
  if (value == null) return [];
  if (Array.isArray(value)) return value.filter((v) => v !== "");
  return value === "" ? [] : [value];
}

function asString(value: string | string[] | undefined): string {
  if (value == null) return "";
  return Array.isArray(value) ? (value[0] ?? "") : value;
}

function asNumber(value: string | string[] | undefined): number | null {
  const s = asString(value).trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

const SORTS = [
  "relevance",
  "price_asc",
  "price_desc",
  "rating_desc",
  "newest",
] as const;

const PAGE_SIZE = 24;

export function parseFilters(params: SearchParams): ParsedFilters {
  const sortRaw = asString(params.sort);
  const sort = (SORTS as readonly string[]).includes(sortRaw)
    ? (sortRaw as ParsedFilters["sort"])
    : "relevance";

  const pageRaw = asNumber(params.page);
  const page = pageRaw && pageRaw > 0 ? Math.floor(pageRaw) : 1;

  // Keep only valid category / condition values to avoid junk in the URL
  // poisoning the query.
  const categories = asArray(params.category).filter((c) =>
    (CATEGORIES as readonly string[]).includes(c),
  );
  const conditions = asArray(params.condition).filter((c) =>
    (CONDITIONS as readonly string[]).includes(c),
  );

  return {
    q: asString(params.q).trim(),
    categories,
    brands: asArray(params.brand),
    conditions,
    minPrice: asNumber(params.minPrice),
    maxPrice: asNumber(params.maxPrice),
    location: asString(params.location).trim(),
    sort,
    page,
    pageSize: PAGE_SIZE,
  };
}

// Build a Prisma where clause from parsed filters for a given site.
export function buildWhere(site: string, f: ParsedFilters) {
  const where: Record<string, unknown> = { site };

  const and: Record<string, unknown>[] = [];

  if (f.q) {
    // SQLite "contains" is case-sensitive in Prisma; we lower-case the title at
    // query time is not possible, so we match against title/brand/category with
    // contains. Good enough for the demo; agents typically use facets.
    and.push({
      OR: [
        { title: { contains: f.q } },
        { brand: { contains: f.q } },
        { category: { contains: f.q } },
        { description: { contains: f.q } },
      ],
    });
  }
  if (f.categories.length) where.category = { in: f.categories };
  if (f.brands.length) where.brand = { in: f.brands };
  if (f.conditions.length) where.condition = { in: f.conditions };
  if (f.location) where.city = f.location;

  const price: Record<string, number> = {};
  if (f.minPrice != null) price.gte = Math.round(f.minPrice * 100);
  if (f.maxPrice != null) price.lte = Math.round(f.maxPrice * 100);
  if (Object.keys(price).length) where.priceCents = price;

  if (and.length) where.AND = and;

  return where;
}

export function buildOrderBy(f: ParsedFilters) {
  switch (f.sort) {
    case "price_asc":
      return [{ priceCents: "asc" as const }, { id: "asc" as const }];
    case "price_desc":
      return [{ priceCents: "desc" as const }, { id: "asc" as const }];
    case "rating_desc":
      return [{ sellerRating: "desc" as const }, { id: "asc" as const }];
    case "newest":
      return [{ createdAt: "desc" as const }, { id: "asc" as const }];
    case "relevance":
    default:
      return [{ id: "asc" as const }];
  }
}

// Serialize parsed filters back to a query string, optionally overriding keys.
// Used to build pagination / sort / facet-toggle links that preserve state.
export function buildQueryString(
  f: ParsedFilters,
  overrides: Partial<{
    q: string;
    categories: string[];
    brands: string[];
    conditions: string[];
    minPrice: number | null;
    maxPrice: number | null;
    location: string;
    sort: string;
    page: number;
  }> = {},
): string {
  const merged = { ...f, ...overrides };
  const sp = new URLSearchParams();

  if (merged.q) sp.set("q", merged.q);
  for (const c of merged.categories) sp.append("category", c);
  for (const b of merged.brands) sp.append("brand", b);
  for (const c of merged.conditions) sp.append("condition", c);
  if (merged.minPrice != null) sp.set("minPrice", String(merged.minPrice));
  if (merged.maxPrice != null) sp.set("maxPrice", String(merged.maxPrice));
  if (merged.location) sp.set("location", merged.location);
  if (merged.sort && merged.sort !== "relevance") sp.set("sort", merged.sort);
  if (merged.page && merged.page > 1) sp.set("page", String(merged.page));

  const s = sp.toString();
  return s ? `?${s}` : "";
}

// Are any filters / search active? (drives whether SEARCH/FILTER events fire)
export function hasActiveFilters(f: ParsedFilters): boolean {
  return Boolean(
    f.q ||
      f.categories.length ||
      f.brands.length ||
      f.conditions.length ||
      f.minPrice != null ||
      f.maxPrice != null ||
      f.location,
  );
}
