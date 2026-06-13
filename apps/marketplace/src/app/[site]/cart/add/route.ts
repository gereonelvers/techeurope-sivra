import { NextRequest, NextResponse } from "next/server";
import { emitEvent } from "@/lib/events";
import { addToCart, getEpisodeId } from "@/lib/session";
import { isSite } from "@/lib/types";

export const dynamic = "force-dynamic";

// POST /[site]/cart/add  (form: listingId) -> add to cart, emit ADD_TO_CART,
// redirect to the cart. Plain form handler (no client JS / server-action
// hydration) so a browser agent OR any HTTP client can drive it.
export async function POST(
  req: NextRequest,
  { params }: { params: { site: string } },
) {
  const site = params.site;
  if (!isSite(site)) {
    return NextResponse.redirect(new URL("/site-a", req.url));
  }

  const form = await req.formData();
  const listingId = Number(form.get("listingId"));

  if (Number.isFinite(listingId)) {
    addToCart(site, listingId);
    const episodeId = getEpisodeId();
    if (episodeId) {
      await emitEvent(episodeId, site, "ADD_TO_CART", { itemId: listingId });
    }
  }

  return NextResponse.redirect(new URL(`/${site}/cart`, req.url), {
    status: 303,
  });
}
