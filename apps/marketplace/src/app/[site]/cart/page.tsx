import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/db";
import { getSkin } from "@/lib/skins";
import { getCart } from "@/lib/session";
import { formatPrice } from "@/lib/format";
import { isSite, Site } from "@/lib/types";

export const dynamic = "force-dynamic";

// Cart page. Cart is stored in a per-site cookie. "Checkout" emits
// CHECKOUT_STARTED (via the server action) and goes to /[site]/checkout.
export default async function CartPage({
  params,
}: {
  params: { site: string };
}) {
  if (!isSite(params.site)) notFound();
  const site = params.site as Site;
  const skin = getSkin(site);
  const t = skin.theme;

  const ids = getCart(site);
  const items = ids.length
    ? await prisma.listing.findMany({ where: { id: { in: ids }, site } })
    : [];

  const totalCents = items.reduce((sum, i) => sum + i.priceCents, 0);

  return (
    <div data-qm="cart-page">
      <h1 className={`mb-4 text-2xl ${t.fontTitle}`}>Your cart</h1>

      {items.length === 0 ? (
        <div
          className={`${t.surface} ${t.radius} border ${t.surfaceBorder} p-8 text-center ${t.mutedText}`}
          data-qm="cart-empty"
        >
          Your cart is empty.{" "}
          <Link href={`/${site}`} className="font-medium underline">
            Browse listings
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <ul className="flex flex-col gap-2" data-qm="cart-items">
            {items.map((i) => (
              <li
                key={i.id}
                data-qm={`cart-item-${i.id}`}
                className={`flex items-center gap-3 ${t.surface} ${t.radius} border ${t.surfaceBorder} p-3`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={i.imageUrl}
                  alt={i.title}
                  width={72}
                  height={54}
                  className="h-[54px] w-[72px] flex-none rounded object-cover"
                />
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/${site}/item/${i.id}`}
                    className={`block truncate font-semibold ${t.bodyText}`}
                  >
                    {i.title}
                  </Link>
                  <span className={`text-xs ${t.mutedText}`}>
                    {i.condition} · {i.city}
                  </span>
                </div>
                <span className={`font-bold ${t.priceText}`}>
                  {formatPrice(i.priceCents, i.currency)}
                </span>
                <form method="POST" action={`/${site}/cart/remove`}>
                  <input type="hidden" name="listingId" value={i.id} />
                  <button
                    type="submit"
                    data-qm={`remove-from-cart-${i.id}`}
                    aria-label={`Remove ${i.title} from cart`}
                    className={`${t.radius} border ${t.surfaceBorder} px-2 py-1 text-xs ${t.mutedText}`}
                  >
                    Remove
                  </button>
                </form>
              </li>
            ))}
          </ul>

          <div
            className={`flex items-center justify-between ${t.surface} ${t.radius} border ${t.surfaceBorder} p-4`}
          >
            <span className={`text-lg font-semibold ${t.bodyText}`}>Total</span>
            <span className={`text-xl font-black ${t.priceText}`} data-qm="cart-total">
              {formatPrice(totalCents, items[0]?.currency ?? "EUR")}
            </span>
          </div>

          <form
            method="POST"
            action={`/${site}/checkout/start`}
            className="self-end"
          >
            <button
              type="submit"
              data-qm="checkout"
              aria-label="Proceed to checkout"
              className={`${t.accent} ${t.accentHover} ${t.accentText} ${t.radius} px-6 py-3 text-base font-semibold`}
            >
              Checkout
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
