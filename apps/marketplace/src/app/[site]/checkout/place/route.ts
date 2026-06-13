import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { emitEvent } from "@/lib/events";
import { clearCart, getCart, getEpisodeId } from "@/lib/session";
import { isSite } from "@/lib/types";

export const dynamic = "force-dynamic";

// POST /[site]/checkout/place -> emit one ORDER_PLACED per cart item (recording
// itemId, priceCents, attrs), clear the cart, redirect to confirmation.
export async function POST(
  req: NextRequest,
  { params }: { params: { site: string } },
) {
  const site = params.site;
  if (!isSite(site)) {
    return NextResponse.redirect(new URL("/site-a", req.url));
  }

  const cart = getCart(site);
  if (cart.length === 0) {
    return NextResponse.redirect(new URL(`/${site}/cart`, req.url), {
      status: 303,
    });
  }

  const episodeId = getEpisodeId();
  const listings = await prisma.listing.findMany({
    where: { id: { in: cart }, site },
  });

  let lastItemId: number | null = null;
  for (const listing of listings) {
    lastItemId = listing.id;
    if (episodeId) {
      await emitEvent(episodeId, site, "ORDER_PLACED", {
        itemId: listing.id,
        priceCents: listing.priceCents,
        attrs: {
          category: listing.category,
          brand: listing.brand,
          condition: listing.condition,
          priceCents: listing.priceCents,
          city: listing.city,
        },
      });
    }
  }

  clearCart(site);

  const url = new URL(`/${site}/confirmation`, req.url);
  if (lastItemId != null) url.searchParams.set("item", String(lastItemId));
  return NextResponse.redirect(url, { status: 303 });
}
