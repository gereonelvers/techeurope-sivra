import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/db";
import { getSkin } from "@/lib/skins";
import { getEpisodeId } from "@/lib/session";
import { emitEventDeduped } from "@/lib/events";
import { formatPrice } from "@/lib/format";
import { isSite, Site } from "@/lib/types";

export const dynamic = "force-dynamic";

// Product detail. Emits PRODUCT_VIEWED on render. Add-to-cart is a server-action
// <form> so it works without client JS.
export default async function ItemPage({
  params,
}: {
  params: { site: string; id: string };
}) {
  if (!isSite(params.site)) notFound();
  const site = params.site as Site;
  const skin = getSkin(site);
  const t = skin.theme;

  const id = Number(params.id);
  if (!Number.isFinite(id)) notFound();

  const listing = await prisma.listing.findFirst({
    where: { id, site },
  });
  if (!listing) notFound();

  // ---- event instrumentation -------------------------------------------
  const episodeId = getEpisodeId();
  if (episodeId) {
    await emitEventDeduped(episodeId, site, "PRODUCT_VIEWED", {
      itemId: listing.id,
    });
  }

  return (
    <article data-qm="product-detail" data-item-id={listing.id}>
      <nav className={`mb-3 text-sm ${t.mutedText}`} aria-label="Breadcrumb">
        <Link href={`/${site}`} data-qm="back-to-results" className="hover:underline">
          ← Back to results
        </Link>
      </nav>

      <div className="grid gap-6 md:grid-cols-2">
        <div className={`overflow-hidden ${t.radius} border ${t.surfaceBorder}`}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={listing.imageUrl}
            alt={listing.title}
            width={400}
            height={300}
            className="aspect-[4/3] w-full object-cover"
            data-qm="product-image"
          />
        </div>

        <div className={`flex flex-col gap-3 ${t.surface} ${t.radius} border ${t.surfaceBorder} p-5`}>
          <div>
            <span
              className={`inline-block ${t.accentSoft} ${t.accentSoftText} ${t.radius} px-2 py-0.5 text-xs font-medium`}
            >
              {listing.category}
            </span>
          </div>
          <h1 className={`text-2xl ${t.fontTitle} ${t.bodyText}`} data-qm="product-title">
            {listing.title}
          </h1>
          <p className={`text-3xl font-black ${t.priceText}`} data-qm="product-price">
            {formatPrice(listing.priceCents, listing.currency)}
          </p>

          <dl className={`grid grid-cols-2 gap-x-4 gap-y-1 text-sm ${t.bodyText}`}>
            <dt className={t.mutedText}>Brand</dt>
            <dd data-qm="product-brand">{listing.brand}</dd>
            <dt className={t.mutedText}>Condition</dt>
            <dd data-qm="product-condition">{listing.condition}</dd>
            <dt className={t.mutedText}>Location</dt>
            <dd data-qm="product-city">{listing.city}</dd>
            <dt className={t.mutedText}>Seller</dt>
            <dd data-qm="product-seller">
              {listing.sellerName} (⭐ {listing.sellerRating.toFixed(1)})
            </dd>
          </dl>

          <p className={`text-sm ${t.bodyText}`} data-qm="product-description">
            {listing.description}
          </p>

          <form
            method="POST"
            action={`/${site}/cart/add`}
            className="mt-auto pt-2"
          >
            <input type="hidden" name="listingId" value={listing.id} />
            <button
              type="submit"
              data-qm="add-to-cart"
              aria-label={`Add ${listing.title} to cart`}
              className={`w-full ${t.accent} ${t.accentHover} ${t.accentText} ${t.radius} px-4 py-3 text-base font-semibold`}
            >
              Add to cart
            </button>
          </form>
        </div>
      </div>
    </article>
  );
}
