import { cookies } from "next/headers";

// Cookie names.
export const EPISODE_COOKIE = "episode_id";
const CART_COOKIE_PREFIX = "cart_"; // cart is per-site: cart_site-a, etc.

const COOKIE_OPTS = {
  httpOnly: false, // readable by an automation agent / debugging; demo app.
  sameSite: "lax" as const,
  path: "/",
  maxAge: 60 * 60 * 24 * 7,
};

/** Read the current episode id from the request cookie (or null). */
export function getEpisodeId(): string | null {
  return cookies().get(EPISODE_COOKIE)?.value ?? null;
}

/** Set the current episode cookie (call from a route handler / server action). */
export function setEpisodeId(episodeId: string): void {
  cookies().set(EPISODE_COOKIE, episodeId, COOKIE_OPTS);
}

function cartCookieName(site: string): string {
  return `${CART_COOKIE_PREFIX}${site}`;
}

/** Read the cart (list of listing ids) for a site from its cookie. */
export function getCart(site: string): number[] {
  const raw = cookies().get(cartCookieName(site))?.value;
  if (!raw) return [];
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    if (Array.isArray(parsed)) {
      return parsed.filter((x) => typeof x === "number");
    }
    return [];
  } catch {
    return [];
  }
}

/** Persist the cart for a site. */
export function setCart(site: string, ids: number[]): void {
  cookies().set(
    cartCookieName(site),
    encodeURIComponent(JSON.stringify(ids)),
    COOKIE_OPTS,
  );
}

/** Add an item to a site's cart (deduped). */
export function addToCart(site: string, listingId: number): void {
  const cart = getCart(site);
  if (!cart.includes(listingId)) {
    cart.push(listingId);
    setCart(site, cart);
  }
}

/** Empty a site's cart. */
export function clearCart(site: string): void {
  setCart(site, []);
}
