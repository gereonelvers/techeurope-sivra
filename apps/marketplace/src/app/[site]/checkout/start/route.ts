import { NextRequest, NextResponse } from "next/server";
import { emitEvent } from "@/lib/events";
import { getCart, getEpisodeId } from "@/lib/session";
import { isSite } from "@/lib/types";

export const dynamic = "force-dynamic";

// POST /[site]/checkout/start -> emit CHECKOUT_STARTED, go to checkout form.
export async function POST(
  req: NextRequest,
  { params }: { params: { site: string } },
) {
  const site = params.site;
  if (!isSite(site)) {
    return NextResponse.redirect(new URL("/site-a", req.url));
  }

  // Don't start checkout with an empty cart.
  if (getCart(site).length === 0) {
    return NextResponse.redirect(new URL(`/${site}/cart`, req.url), {
      status: 303,
    });
  }

  const episodeId = getEpisodeId();
  if (episodeId) {
    await emitEvent(episodeId, site, "CHECKOUT_STARTED", {});
  }

  return NextResponse.redirect(new URL(`/${site}/checkout`, req.url), {
    status: 303,
  });
}
