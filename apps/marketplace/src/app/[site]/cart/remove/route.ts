import { NextRequest, NextResponse } from "next/server";
import { getCart, setCart } from "@/lib/session";
import { isSite } from "@/lib/types";

export const dynamic = "force-dynamic";

// POST /[site]/cart/remove (form: listingId) -> remove from cart, back to cart.
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
    const next = getCart(site).filter((id) => id !== listingId);
    setCart(site, next);
  }

  return NextResponse.redirect(new URL(`/${site}/cart`, req.url), {
    status: 303,
  });
}
