import { Skin } from "@/lib/skins";
import { ParsedFilters } from "@/lib/query";
import { CATEGORIES, CITIES, CONDITIONS, Site } from "@/lib/types";

interface FacetData {
  brands: string[]; // available brands for the current category context
}

// A single GET <form> containing every facet. All state ends up in the URL so
// the page is fully server-rendered and an agent can drive it via the query
// string. `layout` adapts the visual arrangement per skin.
export function FacetPanel({
  skin,
  site,
  filters,
  facetData,
  layout,
}: {
  skin: Skin;
  site: Site;
  filters: ParsedFilters;
  facetData: FacetData;
  layout: "left" | "top" | "right";
}) {
  const t = skin.theme;
  const horizontal = layout === "top";

  return (
    <form
      method="GET"
      action={`/${site}`}
      data-qm="facets"
      aria-label="Filter listings"
      className={
        horizontal
          ? "flex flex-col gap-3"
          : `${t.surface} ${t.radius} border ${t.surfaceBorder} p-4`
      }
    >
      {/* Preserve the active search query across facet submissions. */}
      {filters.q ? (
        <input type="hidden" name="q" value={filters.q} />
      ) : null}
      {/* Preserve sort across facet submissions. */}
      {filters.sort !== "relevance" ? (
        <input type="hidden" name="sort" value={filters.sort} />
      ) : null}

      <div
        className={
          horizontal
            ? "flex flex-wrap items-start gap-x-8 gap-y-4"
            : "flex flex-col gap-5"
        }
      >
        <FacetGroup label="Category" skin={skin} horizontal={horizontal}>
          {CATEGORIES.map((c) => (
            <CheckboxRow
              key={c}
              name="category"
              value={c}
              label={c}
              checked={filters.categories.includes(c)}
              skin={skin}
              qm={`facet-category-${c}`}
              pill={horizontal}
            />
          ))}
        </FacetGroup>

        {facetData.brands.length > 0 && (
          <FacetGroup label="Brand" skin={skin} horizontal={horizontal}>
            {facetData.brands.map((b) => (
              <CheckboxRow
                key={b}
                name="brand"
                value={b}
                label={b}
                checked={filters.brands.includes(b)}
                skin={skin}
                qm={`facet-brand-${b}`}
                pill={horizontal}
              />
            ))}
          </FacetGroup>
        )}

        <FacetGroup label="Condition" skin={skin} horizontal={horizontal}>
          {CONDITIONS.map((c) => (
            <CheckboxRow
              key={c}
              name="condition"
              value={c}
              label={c}
              checked={filters.conditions.includes(c)}
              skin={skin}
              qm={`facet-condition-${c}`}
              pill={horizontal}
            />
          ))}
        </FacetGroup>

        <FacetGroup label="Price (€)" skin={skin} horizontal={horizontal}>
          <div className="flex items-center gap-2">
            <input
              type="number"
              name="minPrice"
              min={0}
              defaultValue={filters.minPrice ?? ""}
              placeholder="min"
              aria-label="Minimum price in euros"
              data-qm="facet-min-price"
              className={`w-20 rounded border ${t.surfaceBorder} px-2 py-1 text-sm`}
            />
            <span className={t.mutedText}>–</span>
            <input
              type="number"
              name="maxPrice"
              min={0}
              defaultValue={filters.maxPrice ?? ""}
              placeholder="max"
              aria-label="Maximum price in euros"
              data-qm="facet-max-price"
              className={`w-20 rounded border ${t.surfaceBorder} px-2 py-1 text-sm`}
            />
          </div>
        </FacetGroup>

        <FacetGroup label="Location" skin={skin} horizontal={horizontal}>
          <select
            name="location"
            defaultValue={filters.location}
            aria-label="Filter by city"
            data-qm="facet-location"
            className={`rounded border ${t.surfaceBorder} px-2 py-1 text-sm`}
          >
            <option value="">All cities</option>
            {CITIES.map((city) => (
              <option key={city} value={city}>
                {city}
              </option>
            ))}
          </select>
        </FacetGroup>
      </div>

      <div className={horizontal ? "flex gap-2" : "mt-2 flex flex-col gap-2"}>
        <button
          type="submit"
          data-qm="apply-filters"
          aria-label="Apply filters"
          className={`${t.accent} ${t.accentHover} ${t.accentText} ${t.radius} px-4 py-2 text-sm font-medium`}
        >
          Apply filters
        </button>
        <a
          href={`/${site}`}
          data-qm="clear-filters"
          aria-label="Clear all filters"
          className={`${t.radius} border ${t.surfaceBorder} px-4 py-2 text-center text-sm font-medium ${t.bodyText}`}
        >
          Clear
        </a>
      </div>
    </form>
  );
}

function FacetGroup({
  label,
  skin,
  horizontal,
  children,
}: {
  label: string;
  skin: Skin;
  horizontal: boolean;
  children: React.ReactNode;
}) {
  const t = skin.theme;
  return (
    <fieldset
      className={horizontal ? "" : "border-0 p-0"}
      data-qm={`facet-group-${label.toLowerCase().split(" ")[0]}`}
    >
      <legend
        className={`mb-1.5 text-xs font-semibold uppercase tracking-wide ${t.mutedText}`}
      >
        {label}
      </legend>
      <div
        className={
          horizontal ? "flex flex-wrap gap-1.5" : "flex flex-col gap-1"
        }
      >
        {children}
      </div>
    </fieldset>
  );
}

function CheckboxRow({
  name,
  value,
  label,
  checked,
  skin,
  qm,
  pill,
}: {
  name: string;
  value: string;
  label: string;
  checked: boolean;
  skin: Skin;
  qm: string;
  pill: boolean;
}) {
  const t = skin.theme;

  if (pill) {
    // Top-pill layout (site-b): label styled as a toggle chip.
    return (
      <label
        className={`cursor-pointer select-none ${t.radius} border px-3 py-1 text-sm ${
          checked
            ? `${t.accent} ${t.accentText} border-transparent`
            : `${t.surface} ${t.surfaceBorder} ${t.bodyText}`
        }`}
      >
        <input
          type="checkbox"
          name={name}
          value={value}
          defaultChecked={checked}
          data-qm={qm}
          aria-label={`${name} ${value}`}
          className="sr-only"
        />
        {label}
      </label>
    );
  }

  return (
    <label
      className={`flex cursor-pointer items-center gap-2 text-sm ${t.bodyText}`}
    >
      <input
        type="checkbox"
        name={name}
        value={value}
        defaultChecked={checked}
        data-qm={qm}
        aria-label={`${name} ${value}`}
        className="h-4 w-4"
      />
      {label}
    </label>
  );
}
