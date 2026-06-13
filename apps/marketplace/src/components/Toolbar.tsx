import { Skin } from "@/lib/skins";
import { buildQueryString, ParsedFilters } from "@/lib/query";
import { Site } from "@/lib/types";

const SORT_OPTIONS: { value: ParsedFilters["sort"]; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "price_asc", label: "Price: low to high" },
  { value: "price_desc", label: "Price: high to low" },
  { value: "rating_desc", label: "Seller rating" },
  { value: "newest", label: "Newest" },
];

// Result count + sort <select> (a GET form preserving all current filters) +
// page navigation. Sort and page both live in the URL.
export function Toolbar({
  skin,
  site,
  filters,
  total,
}: {
  skin: Skin;
  site: Site;
  filters: ParsedFilters;
  total: number;
}) {
  const t = skin.theme;
  const start = total === 0 ? 0 : (filters.page - 1) * filters.pageSize + 1;
  const end = Math.min(filters.page * filters.pageSize, total);

  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <p className={`text-sm ${t.mutedText}`} data-qm="result-count">
        {total === 0
          ? "0 results"
          : `${start}–${end} of ${total} results`}
      </p>

      <form method="GET" action={`/${site}`} className="flex items-center gap-2">
        {/* Preserve all active filters when changing sort. */}
        {filters.q ? <input type="hidden" name="q" value={filters.q} /> : null}
        {filters.categories.map((c) => (
          <input key={c} type="hidden" name="category" value={c} />
        ))}
        {filters.brands.map((b) => (
          <input key={b} type="hidden" name="brand" value={b} />
        ))}
        {filters.conditions.map((c) => (
          <input key={c} type="hidden" name="condition" value={c} />
        ))}
        {filters.minPrice != null ? (
          <input type="hidden" name="minPrice" value={filters.minPrice} />
        ) : null}
        {filters.maxPrice != null ? (
          <input type="hidden" name="maxPrice" value={filters.maxPrice} />
        ) : null}
        {filters.location ? (
          <input type="hidden" name="location" value={filters.location} />
        ) : null}

        <label className={`text-sm ${t.mutedText}`} htmlFor="sort-select">
          Sort
        </label>
        <select
          id="sort-select"
          name="sort"
          defaultValue={filters.sort}
          data-qm="sort"
          aria-label="Sort results"
          className={`rounded border ${t.surfaceBorder} px-2 py-1 text-sm ${t.bodyText}`}
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <button
          type="submit"
          data-qm="sort-apply"
          aria-label="Apply sort"
          className={`${t.radius} border ${t.surfaceBorder} px-2 py-1 text-sm ${t.bodyText}`}
        >
          Go
        </button>
      </form>
    </div>
  );
}

export function Pagination({
  skin,
  site,
  filters,
  total,
}: {
  skin: Skin;
  site: Site;
  filters: ParsedFilters;
  total: number;
}) {
  const t = skin.theme;
  const totalPages = Math.max(1, Math.ceil(total / filters.pageSize));
  if (totalPages <= 1) return null;

  const page = filters.page;
  const prevHref = `/${site}${buildQueryString(filters, { page: page - 1 })}`;
  const nextHref = `/${site}${buildQueryString(filters, { page: page + 1 })}`;

  // Show a compact window of page numbers.
  const windowSize = 5;
  const startPage = Math.max(1, Math.min(page - 2, totalPages - windowSize + 1));
  const pages: number[] = [];
  for (let p = startPage; p < startPage + windowSize && p <= totalPages; p++) {
    pages.push(p);
  }

  return (
    <nav
      className="mt-6 flex items-center justify-center gap-1"
      aria-label="Pagination"
      data-qm="pagination"
    >
      {page > 1 && (
        <a
          href={prevHref}
          data-qm="page-prev"
          aria-label="Previous page"
          className={`${t.radius} border ${t.surfaceBorder} px-3 py-1.5 text-sm ${t.bodyText}`}
        >
          ‹ Prev
        </a>
      )}
      {pages.map((p) => (
        <a
          key={p}
          href={`/${site}${buildQueryString(filters, { page: p })}`}
          data-qm={`page-${p}`}
          aria-label={`Page ${p}`}
          aria-current={p === page ? "page" : undefined}
          className={`${t.radius} px-3 py-1.5 text-sm ${
            p === page
              ? `${t.accent} ${t.accentText}`
              : `border ${t.surfaceBorder} ${t.bodyText}`
          }`}
        >
          {p}
        </a>
      ))}
      {page < totalPages && (
        <a
          href={nextHref}
          data-qm="page-next"
          aria-label="Next page"
          className={`${t.radius} border ${t.surfaceBorder} px-3 py-1.5 text-sm ${t.bodyText}`}
        >
          Next ›
        </a>
      )}
    </nav>
  );
}
