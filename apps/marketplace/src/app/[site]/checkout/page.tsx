import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { prisma } from "@/lib/db";
import { getSkin } from "@/lib/skins";
import { getCart } from "@/lib/session";
import { formatPrice } from "@/lib/format";
import { isSite, Site } from "@/lib/types";

export const dynamic = "force-dynamic";

// Checkout form. "Place order" runs the placeOrderAction server action which
// emits ORDER_PLACED for each cart item and redirects to confirmation.
export default async function CheckoutPage({
  params,
}: {
  params: { site: string };
}) {
  if (!isSite(params.site)) notFound();
  const site = params.site as Site;
  const skin = getSkin(site);
  const t = skin.theme;

  const ids = getCart(site);
  if (ids.length === 0) {
    redirect(`/${site}/cart`);
  }

  const items = await prisma.listing.findMany({
    where: { id: { in: ids }, site },
  });
  const totalCents = items.reduce((sum, i) => sum + i.priceCents, 0);

  return (
    <div data-qm="checkout-page">
      <h1 className={`mb-4 text-2xl ${t.fontTitle}`}>Checkout</h1>

      <form
        method="POST"
        action={`/${site}/checkout/place`}
        className="grid gap-6 md:grid-cols-3"
      >

        {/* Address + shipping form */}
        <div className="md:col-span-2">
          <fieldset
            className={`${t.surface} ${t.radius} border ${t.surfaceBorder} p-5`}
          >
            <legend className={`px-1 text-sm font-semibold ${t.mutedText}`}>
              Shipping address
            </legend>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                t={t}
                label="Full name"
                name="fullName"
                qm="checkout-name"
                defaultValue="Test Buyer"
                required
              />
              <Field
                t={t}
                label="Email"
                name="email"
                type="email"
                qm="checkout-email"
                defaultValue="buyer@example.com"
                required
              />
              <div className="sm:col-span-2">
                <Field
                  t={t}
                  label="Street address"
                  name="street"
                  qm="checkout-street"
                  defaultValue="Marienplatz 1"
                  required
                />
              </div>
              <Field
                t={t}
                label="City"
                name="city"
                qm="checkout-city"
                defaultValue="München"
                required
              />
              <Field
                t={t}
                label="Postal code"
                name="zip"
                qm="checkout-zip"
                defaultValue="80331"
                required
              />
            </div>

            <fieldset className="mt-5">
              <legend className={`text-sm font-semibold ${t.mutedText}`}>
                Shipping method
              </legend>
              <div className="mt-2 flex flex-col gap-2">
                <label className={`flex items-center gap-2 text-sm ${t.bodyText}`}>
                  <input
                    type="radio"
                    name="shipping"
                    value="standard"
                    defaultChecked
                    data-qm="shipping-standard"
                    aria-label="Standard shipping"
                  />
                  Standard (3–5 days) — free
                </label>
                <label className={`flex items-center gap-2 text-sm ${t.bodyText}`}>
                  <input
                    type="radio"
                    name="shipping"
                    value="express"
                    data-qm="shipping-express"
                    aria-label="Express shipping"
                  />
                  Express (1–2 days) — €9
                </label>
              </div>
            </fieldset>
          </fieldset>
        </div>

        {/* Order summary + place order */}
        <aside
          className={`flex h-fit flex-col gap-3 ${t.surface} ${t.radius} border ${t.surfaceBorder} p-5`}
          data-qm="order-summary"
        >
          <h2 className={`text-sm font-semibold ${t.mutedText}`}>Order summary</h2>
          <ul className="flex flex-col gap-2">
            {items.map((i) => (
              <li
                key={i.id}
                className={`flex justify-between gap-2 text-sm ${t.bodyText}`}
                data-qm={`summary-item-${i.id}`}
              >
                <span className="truncate">{i.title}</span>
                <span className="whitespace-nowrap font-medium">
                  {formatPrice(i.priceCents, i.currency)}
                </span>
              </li>
            ))}
          </ul>
          <div className={`flex justify-between border-t ${t.surfaceBorder} pt-2`}>
            <span className={`font-semibold ${t.bodyText}`}>Total</span>
            <span className={`font-black ${t.priceText}`} data-qm="checkout-total">
              {formatPrice(totalCents, items[0]?.currency ?? "EUR")}
            </span>
          </div>

          <button
            type="submit"
            data-qm="place-order"
            aria-label="Place order"
            className={`mt-2 w-full ${t.accent} ${t.accentHover} ${t.accentText} ${t.radius} px-4 py-3 text-base font-semibold`}
          >
            Place order
          </button>
          <Link
            href={`/${site}/cart`}
            data-qm="back-to-cart"
            className={`text-center text-sm underline ${t.mutedText}`}
          >
            Back to cart
          </Link>
        </aside>
      </form>
    </div>
  );
}

function Field({
  t,
  label,
  name,
  qm,
  type = "text",
  defaultValue,
  required,
}: {
  t: ReturnType<typeof getSkin>["theme"];
  label: string;
  name: string;
  qm: string;
  type?: string;
  defaultValue?: string;
  required?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className={t.mutedText}>{label}</span>
      <input
        type={type}
        name={name}
        defaultValue={defaultValue}
        required={required}
        data-qm={qm}
        aria-label={label}
        className={`rounded border ${t.surfaceBorder} px-3 py-2 text-sm ${t.bodyText}`}
      />
    </label>
  );
}
