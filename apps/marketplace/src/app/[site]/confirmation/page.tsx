import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/db";
import { getSkin } from "@/lib/skins";
import { formatPrice } from "@/lib/format";
import { isSite, Site } from "@/lib/types";
import { SearchParams } from "@/lib/query";

export const dynamic = "force-dynamic";

// Order confirmation. Shows the ordered item (passed via ?item=<id>). The
// ORDER_PLACED event was already emitted by the placeOrderAction.
export default async function ConfirmationPage({
  params,
  searchParams,
}: {
  params: { site: string };
  searchParams: SearchParams;
}) {
  if (!isSite(params.site)) notFound();
  const site = params.site as Site;
  const skin = getSkin(site);
  const t = skin.theme;

  const itemParam = searchParams.item;
  const itemId = itemParam
    ? Number(Array.isArray(itemParam) ? itemParam[0] : itemParam)
    : NaN;
  const item = Number.isFinite(itemId)
    ? await prisma.listing.findFirst({ where: { id: itemId, site } })
    : null;

  return (
    <div data-qm="confirmation-page" className="mx-auto max-w-lg text-center">
      <div className="mb-4 text-5xl" aria-hidden="true">
        ✅
      </div>
      <h1 className={`mb-2 text-2xl ${t.fontTitle}`} data-qm="order-confirmed">
        Order confirmed!
      </h1>
      <p className={`mb-6 ${t.mutedText}`}>
        Thanks for your purchase. A confirmation has been recorded.
      </p>

      {item ? (
        <div
          className={`mx-auto flex max-w-md items-center gap-3 ${t.surface} ${t.radius} border ${t.surfaceBorder} p-4 text-left`}
          data-qm="confirmation-item"
          data-item-id={item.id}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={item.imageUrl}
            alt={item.title}
            width={96}
            height={72}
            className="h-[72px] w-[96px] flex-none rounded object-cover"
          />
          <div className="min-w-0">
            <p className={`truncate font-semibold ${t.bodyText}`}>{item.title}</p>
            <p className={`text-sm ${t.mutedText}`}>
              {item.condition} · {item.city}
            </p>
            <p className={`font-bold ${t.priceText}`}>
              {formatPrice(item.priceCents, item.currency)}
            </p>
          </div>
        </div>
      ) : null}

      <div className="mt-6">
        <Link
          href={`/${site}`}
          data-qm="continue-shopping"
          className={`inline-block ${t.accent} ${t.accentHover} ${t.accentText} ${t.radius} px-6 py-3 font-semibold`}
        >
          Continue shopping
        </Link>
      </div>
    </div>
  );
}
