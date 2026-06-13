import Link from "next/link";
import { Skin } from "@/lib/skins";
import { formatPrice } from "@/lib/format";
import { Site } from "@/lib/types";

export interface ListingCard {
  id: number;
  title: string;
  category: string;
  brand: string;
  condition: string;
  priceCents: number;
  currency: string;
  city: string;
  sellerName: string;
  sellerRating: number;
  imageUrl: string;
}

// Switches between the three visually-distinct result layouts. Every listing
// is a link to its detail page and carries data-qm="listing-<id>".
export function Results({
  skin,
  site,
  listings,
}: {
  skin: Skin;
  site: Site;
  listings: ListingCard[];
}) {
  if (listings.length === 0) {
    return (
      <div
        className={`${skin.theme.mutedText} ${skin.theme.surface} ${skin.theme.radius} border ${skin.theme.surfaceBorder} p-8 text-center`}
        data-qm="no-results"
      >
        No listings match your filters.
      </div>
    );
  }

  switch (skin.resultsLayout) {
    case "cards":
      return <CardGrid skin={skin} site={site} listings={listings} />;
    case "table":
      return <ResultsTable skin={skin} site={site} listings={listings} />;
    case "rows":
    default:
      return <RowList skin={skin} site={site} listings={listings} />;
  }
}

// ---- site-a: dense compact rows ------------------------------------------
function RowList({
  skin,
  site,
  listings,
}: {
  skin: Skin;
  site: Site;
  listings: ListingCard[];
}) {
  const t = skin.theme;
  return (
    <ul className="flex flex-col gap-2" data-qm="results">
      {listings.map((l) => (
        <li key={l.id}>
          <Link
            href={`/${site}/item/${l.id}`}
            data-qm={`listing-${l.id}`}
            aria-label={`${l.title}, ${formatPrice(l.priceCents, l.currency)}, ${l.condition}`}
            className={`flex gap-3 ${t.surface} border ${t.surfaceBorder} ${t.radius} p-2 hover:border-emerald-400`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={l.imageUrl}
              alt={l.title}
              width={120}
              height={90}
              className="h-[90px] w-[120px] flex-none rounded object-cover"
            />
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-start justify-between gap-2">
                <span className={`truncate text-sm font-semibold ${t.bodyText}`}>
                  {l.title}
                </span>
                <span className={`whitespace-nowrap text-sm font-bold ${t.priceText}`} data-qm={`price-${l.id}`}>
                  {formatPrice(l.priceCents, l.currency)}
                </span>
              </div>
              <span className={`text-xs ${t.mutedText}`}>
                {l.category} · {l.brand} · {l.condition}
              </span>
              <span className={`mt-auto text-xs ${t.mutedText}`}>
                📍 {l.city} · ⭐ {l.sellerRating.toFixed(1)} {l.sellerName}
              </span>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

// ---- site-b: big image-grid cards ----------------------------------------
function CardGrid({
  skin,
  site,
  listings,
}: {
  skin: Skin;
  site: Site;
  listings: ListingCard[];
}) {
  const t = skin.theme;
  return (
    <div
      className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4"
      data-qm="results"
    >
      {listings.map((l) => (
        <Link
          key={l.id}
          href={`/${site}/item/${l.id}`}
          data-qm={`listing-${l.id}`}
          aria-label={`${l.title}, ${formatPrice(l.priceCents, l.currency)}, ${l.condition}`}
          className={`group flex flex-col overflow-hidden ${t.surface} border ${t.surfaceBorder} ${t.radius} transition hover:shadow-lg`}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={l.imageUrl}
            alt={l.title}
            width={400}
            height={300}
            className="aspect-[4/3] w-full object-cover transition group-hover:scale-[1.02]"
          />
          <div className="flex flex-1 flex-col p-3 text-center">
            <span className={`truncate text-sm font-bold ${t.bodyText}`}>
              {l.title}
            </span>
            <span className={`text-xs ${t.mutedText}`}>
              {l.condition} · {l.city}
            </span>
            <span
              className={`mt-2 text-lg font-black ${t.priceText}`}
              data-qm={`price-${l.id}`}
            >
              {formatPrice(l.priceCents, l.currency)}
            </span>
            <span className={`mt-1 text-xs ${t.mutedText}`}>
              ⭐ {l.sellerRating.toFixed(1)}
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}

// ---- site-c: table-like results ------------------------------------------
function ResultsTable({
  skin,
  site,
  listings,
}: {
  skin: Skin;
  site: Site;
  listings: ListingCard[];
}) {
  const t = skin.theme;
  return (
    <div
      className={`overflow-hidden ${t.surface} border ${t.surfaceBorder} ${t.radius}`}
      data-qm="results"
    >
      <table className="w-full border-collapse text-sm">
        <thead className={`${t.accentSoft} ${t.accentSoftText}`}>
          <tr className="text-left">
            <th className="px-3 py-2 font-semibold">Item</th>
            <th className="hidden px-3 py-2 font-semibold sm:table-cell">
              Category
            </th>
            <th className="hidden px-3 py-2 font-semibold md:table-cell">
              Condition
            </th>
            <th className="hidden px-3 py-2 font-semibold lg:table-cell">
              Location
            </th>
            <th className="hidden px-3 py-2 font-semibold lg:table-cell">
              Seller
            </th>
            <th className="px-3 py-2 text-right font-semibold">Price</th>
          </tr>
        </thead>
        <tbody>
          {listings.map((l, i) => (
            <tr
              key={l.id}
              className={`border-t ${t.surfaceBorder} ${i % 2 ? "bg-slate-50/60" : ""} hover:bg-blue-50`}
            >
              <td className="px-3 py-2">
                <Link
                  href={`/${site}/item/${l.id}`}
                  data-qm={`listing-${l.id}`}
                  aria-label={`${l.title}, ${formatPrice(l.priceCents, l.currency)}, ${l.condition}`}
                  className="flex items-center gap-3"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={l.imageUrl}
                    alt={l.title}
                    width={56}
                    height={42}
                    className="h-[42px] w-[56px] flex-none rounded object-cover"
                  />
                  <span className={`font-medium ${t.priceText} hover:underline`}>
                    {l.title}
                  </span>
                </Link>
              </td>
              <td className={`hidden px-3 py-2 sm:table-cell ${t.bodyText}`}>
                {l.category}
              </td>
              <td className={`hidden px-3 py-2 md:table-cell ${t.bodyText}`}>
                {l.condition}
              </td>
              <td className={`hidden px-3 py-2 lg:table-cell ${t.bodyText}`}>
                {l.city}
              </td>
              <td className={`hidden px-3 py-2 lg:table-cell ${t.mutedText}`}>
                ⭐ {l.sellerRating.toFixed(1)}
              </td>
              <td
                className={`px-3 py-2 text-right font-bold ${t.priceText}`}
                data-qm={`price-${l.id}`}
              >
                {formatPrice(l.priceCents, l.currency)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
