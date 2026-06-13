import { Site } from "./types";

// A skin describes the look AND the structural layout choices for a site.
// All three sites share one backend + the same routes; only the skin differs.
export interface Skin {
  site: Site;
  name: string;
  tagline: string;
  // Where the facet panel sits relative to results.
  facetPosition: "left" | "top" | "right";
  // How results are laid out.
  resultsLayout: "rows" | "cards" | "table";
  // Tailwind class fragments. Kept as plain strings so they survive the
  // safelist in tailwind.config.ts.
  theme: {
    appBg: string;
    headerBg: string;
    headerText: string;
    headerBorder: string;
    accent: string; // primary action bg
    accentHover: string;
    accentText: string;
    accentSoft: string; // light accent backgrounds (pills, badges)
    accentSoftText: string;
    accentRing: string;
    surface: string; // card / panel background
    surfaceBorder: string;
    mutedText: string;
    bodyText: string;
    priceText: string;
    radius: string; // rounding scale used by cards/buttons
    fontTitle: string; // header/title weight + tracking
    density: "compact" | "comfortable" | "table";
  };
}

export const SKINS: Record<Site, Skin> = {
  // Kleinanzeigen vibe: dense list, left sidebar, muted grey/green.
  "site-a": {
    site: "site-a",
    name: "Kleinmarkt",
    tagline: "Gebraucht kaufen & verkaufen in deiner Nähe",
    facetPosition: "left",
    resultsLayout: "rows",
    theme: {
      appBg: "bg-stone-100",
      headerBg: "bg-emerald-700",
      headerText: "text-white",
      headerBorder: "border-emerald-800",
      accent: "bg-emerald-600",
      accentHover: "hover:bg-emerald-700",
      accentText: "text-white",
      accentSoft: "bg-emerald-50",
      accentSoftText: "text-emerald-800",
      accentRing: "focus:ring-emerald-500",
      surface: "bg-white",
      surfaceBorder: "border-stone-300",
      mutedText: "text-stone-500",
      bodyText: "text-stone-800",
      priceText: "text-stone-900",
      radius: "rounded",
      fontTitle: "font-semibold tracking-tight",
      density: "compact",
    },
  },
  // Depop/Grailed vibe: large image-grid cards, top filter pills, bold/centered.
  "site-b": {
    site: "site-b",
    name: "GRAINED",
    tagline: "Curated secondhand. Find your grail.",
    facetPosition: "top",
    resultsLayout: "cards",
    theme: {
      appBg: "bg-white",
      headerBg: "bg-black",
      headerText: "text-white",
      headerBorder: "border-black",
      accent: "bg-black",
      accentHover: "hover:bg-zinc-800",
      accentText: "text-white",
      accentSoft: "bg-zinc-100",
      accentSoftText: "text-zinc-900",
      accentRing: "focus:ring-zinc-900",
      surface: "bg-white",
      surfaceBorder: "border-zinc-200",
      mutedText: "text-zinc-500",
      bodyText: "text-zinc-900",
      priceText: "text-black",
      radius: "rounded-2xl",
      fontTitle: "font-black tracking-tight uppercase",
      density: "comfortable",
    },
  },
  // eBay vibe: table-like results, right-rail facets, blue accents.
  "site-c": {
    site: "site-c",
    name: "BidBay",
    tagline: "The marketplace for everything secondhand",
    facetPosition: "right",
    resultsLayout: "table",
    theme: {
      appBg: "bg-slate-50",
      headerBg: "bg-white",
      headerText: "text-slate-900",
      headerBorder: "border-slate-200",
      accent: "bg-blue-600",
      accentHover: "hover:bg-blue-700",
      accentText: "text-white",
      accentSoft: "bg-blue-50",
      accentSoftText: "text-blue-700",
      accentRing: "focus:ring-blue-500",
      surface: "bg-white",
      surfaceBorder: "border-slate-200",
      mutedText: "text-slate-500",
      bodyText: "text-slate-800",
      priceText: "text-blue-700",
      radius: "rounded-md",
      fontTitle: "font-bold tracking-normal",
      density: "table",
    },
  },
};

export function getSkin(site: Site): Skin {
  return SKINS[site];
}
