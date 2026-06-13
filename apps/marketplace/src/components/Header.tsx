import Link from "next/link";
import { Skin } from "@/lib/skins";
import { Site } from "@/lib/types";

// Per-skin header with a search input bound to the GET form on the results page
// (via the `q` query param) and a cart link. The search form posts to the site
// root so filter/search state lives entirely in the URL.
export function Header({
  skin,
  site,
  q,
  cartCount,
}: {
  skin: Skin;
  site: Site;
  q: string;
  cartCount: number;
}) {
  const t = skin.theme;

  return (
    <header
      className={`${t.headerBg} ${t.headerText} border-b ${t.headerBorder}`}
      data-qm="site-header"
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
        <Link
          href={`/${site}`}
          data-qm="logo"
          aria-label={`${skin.name} home`}
          className={`${t.fontTitle} text-xl`}
        >
          {skin.name}
        </Link>

        <form
          method="GET"
          action={`/${site}`}
          role="search"
          aria-label="Search listings"
          className="order-3 flex w-full items-stretch gap-2 sm:order-2 sm:w-auto sm:flex-1"
        >
          <input
            type="search"
            name="q"
            defaultValue={q}
            data-qm="search"
            aria-label="Search query"
            placeholder="Search items, brands, categories…"
            className={`w-full rounded border border-black/10 bg-white px-3 py-2 text-sm text-gray-900 outline-none ${t.accentRing} focus:ring-2`}
          />
          <button
            type="submit"
            data-qm="search-submit"
            aria-label="Submit search"
            className={`${t.accent} ${t.accentHover} ${t.accentText} ${t.radius} px-4 py-2 text-sm font-medium`}
          >
            Search
          </button>
        </form>

        <nav
          className="order-2 ml-auto flex items-center gap-3 sm:order-3"
          aria-label="Main navigation"
        >
          <SkinSwitcher site={site} />
          <Link
            href={`/${site}/cart`}
            data-qm="cart-link"
            aria-label={`Cart, ${cartCount} item${cartCount === 1 ? "" : "s"}`}
            className="inline-flex items-center gap-1 text-sm font-medium"
          >
            <span aria-hidden="true">🛒</span>
            <span data-qm="cart-count">{cartCount}</span>
          </Link>
        </nav>
      </div>
    </header>
  );
}

// Lets a human (and an agent) jump between the three skins of the same backend.
function SkinSwitcher({ site }: { site: Site }) {
  const sites: Site[] = ["site-a", "site-b", "site-c"];
  return (
    <div
      className="hidden items-center gap-1 text-xs opacity-80 sm:flex"
      data-qm="skin-switcher"
      aria-label="Switch skin"
    >
      {sites.map((s) => (
        <Link
          key={s}
          href={`/${s}`}
          data-qm={`skin-${s}`}
          aria-label={`Switch to ${s}`}
          className={`rounded px-1.5 py-0.5 ${
            s === site ? "bg-white/25 font-bold" : "hover:bg-white/15"
          }`}
        >
          {s.replace("site-", "").toUpperCase()}
        </Link>
      ))}
    </div>
  );
}
