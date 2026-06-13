import { notFound } from "next/navigation";
import { prisma } from "@/lib/db";
import { getSkin } from "@/lib/skins";
import { getEpisodeId } from "@/lib/session";
import { emitEventDeduped } from "@/lib/events";
import {
  buildOrderBy,
  buildWhere,
  hasActiveFilters,
  parseFilters,
  SearchParams,
} from "@/lib/query";
import { isSite, Site } from "@/lib/types";
import { FacetPanel } from "@/components/FacetPanel";
import { Results, ListingCard } from "@/components/Results";
import { Pagination, Toolbar } from "@/components/Toolbar";

export const dynamic = "force-dynamic";

// Faceted search/results page. Fully server-rendered; all state in the URL.
// On render, emits SEARCH_SUBMITTED (if q) and FILTER_APPLIED (per active facet)
// for the current episode.
export default async function ResultsPage({
  params,
  searchParams,
}: {
  params: { site: string };
  searchParams: SearchParams;
}) {
  if (!isSite(params.site)) notFound();
  const site = params.site as Site;
  const skin = getSkin(site);

  const filters = parseFilters(searchParams);
  const where = buildWhere(site, filters);
  const orderBy = buildOrderBy(filters);

  const [total, listingsRaw, brandGroups] = await Promise.all([
    prisma.listing.count({ where }),
    prisma.listing.findMany({
      where,
      orderBy,
      skip: (filters.page - 1) * filters.pageSize,
      take: filters.pageSize,
    }),
    // Available brands within the current category context (for the facet list).
    prisma.listing.findMany({
      where: {
        site,
        ...(filters.categories.length
          ? { category: { in: filters.categories } }
          : {}),
      },
      select: { brand: true },
      distinct: ["brand"],
      orderBy: { brand: "asc" },
    }),
  ]);

  const listings: ListingCard[] = listingsRaw.map((l) => ({
    id: l.id,
    title: l.title,
    category: l.category,
    brand: l.brand,
    condition: l.condition,
    priceCents: l.priceCents,
    currency: l.currency,
    city: l.city,
    sellerName: l.sellerName,
    sellerRating: l.sellerRating,
    imageUrl: l.imageUrl,
  }));

  const facetData = {
    brands: brandGroups.map((b) => b.brand),
  };

  // ---- event instrumentation (render-time) -------------------------------
  const episodeId = getEpisodeId();
  if (episodeId) {
    if (filters.q) {
      await emitEventDeduped(episodeId, site, "SEARCH_SUBMITTED", {
        query: filters.q,
      });
    }
    // One FILTER_APPLIED per active facet value, deduped so re-render is a noop.
    const facetEvents: { facet: string; value: string }[] = [];
    for (const c of filters.categories)
      facetEvents.push({ facet: "category", value: c });
    for (const b of filters.brands)
      facetEvents.push({ facet: "brand", value: b });
    for (const c of filters.conditions)
      facetEvents.push({ facet: "condition", value: c });
    if (filters.minPrice != null)
      facetEvents.push({ facet: "minPrice", value: String(filters.minPrice) });
    if (filters.maxPrice != null)
      facetEvents.push({ facet: "maxPrice", value: String(filters.maxPrice) });
    if (filters.location)
      facetEvents.push({ facet: "location", value: filters.location });

    for (const fe of facetEvents) {
      await emitEventDeduped(episodeId, site, "FILTER_APPLIED", fe);
    }
  }

  const facetPanel = (
    <FacetPanel
      skin={skin}
      site={site}
      filters={filters}
      facetData={facetData}
      layout={skin.facetPosition}
    />
  );

  const resultsBlock = (
    <div className="min-w-0 flex-1" data-qm="results-column">
      <Toolbar skin={skin} site={site} filters={filters} total={total} />
      <Results skin={skin} site={site} listings={listings} />
      <Pagination skin={skin} site={site} filters={filters} total={total} />
    </div>
  );

  return (
    <div data-qm="results-page" data-site={site}>
      <div className="mb-4">
        <h1 className={`text-2xl ${skin.theme.fontTitle}`}>{skin.name}</h1>
        <p className={`text-sm ${skin.theme.mutedText}`}>{skin.tagline}</p>
        {hasActiveFilters(filters) ? (
          <p className={`mt-1 text-xs ${skin.theme.mutedText}`} data-qm="active-query">
            {filters.q ? `“${filters.q}” · ` : ""}
            {[
              ...filters.categories,
              ...filters.brands,
              ...filters.conditions,
            ].join(", ")}
          </p>
        ) : null}
      </div>

      {skin.facetPosition === "top" ? (
        // site-b: pills above the grid.
        <div className="flex flex-col gap-4">
          <div
            className={`${skin.theme.surface} border ${skin.theme.surfaceBorder} ${skin.theme.radius} p-4`}
          >
            {facetPanel}
          </div>
          {resultsBlock}
        </div>
      ) : skin.facetPosition === "right" ? (
        // site-c: facets on the right rail.
        <div className="flex flex-col gap-6 md:flex-row-reverse">
          <aside className="w-full md:w-64 md:flex-none" data-qm="facet-rail">
            {facetPanel}
          </aside>
          {resultsBlock}
        </div>
      ) : (
        // site-a: left sidebar.
        <div className="flex flex-col gap-6 md:flex-row">
          <aside className="w-full md:w-60 md:flex-none" data-qm="facet-rail">
            {facetPanel}
          </aside>
          {resultsBlock}
        </div>
      )}
    </div>
  );
}
