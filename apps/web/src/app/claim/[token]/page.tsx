import Link from "next/link";
import { redirect } from "next/navigation";
import { prisma } from "@/lib/db";
import { signIn } from "@/lib/auth";
import { claimAccount } from "@/lib/phone-link";
import { formatPhoneDisplay } from "@/lib/phone";
import { Wordmark } from "@/app/_components/Wordmark";

// /claim/:token — opened from the SMS we text an unknown caller. The token is
// the capability (texted only to the number that called). Finishing here turns
// their provisional account into a real one (email + workspace name) and sends a
// magic link; the order they placed by phone is already waiting inside.
export const dynamic = "force-dynamic";

const euros = (cents: number | null, currency = "EUR") =>
  cents == null
    ? null
    : new Intl.NumberFormat("en-IE", { style: "currency", currency }).format(cents / 100);

export default async function ClaimPage({
  params,
  searchParams,
}: {
  params: { token: string };
  searchParams: { error?: string };
}) {
  const v = await prisma.phoneVerification.findUnique({ where: { token: params.token } });
  const valid =
    !!v && v.kind === "CLAIM" && !v.consumedAt && v.expiresAt > new Date();
  const order =
    valid && v?.orderId
      ? await prisma.order.findUnique({
          where: { id: v.orderId },
          select: {
            title: true,
            status: true,
            resultTitle: true,
            resultPriceCents: true,
            currency: true,
          },
        })
      : null;

  // Server action — claim the account, then kick the normal magic-link sign-in.
  async function finishClaim(formData: FormData) {
    "use server";
    const email = String(formData.get("email") ?? "").trim();
    const orgName = String(formData.get("orgName") ?? "").trim();
    const result = await claimAccount(params.token, email, orgName);
    if (!result.ok) {
      redirect(
        `/claim/${params.token}?error=${encodeURIComponent(
          result.error ?? "Could not finish sign-up.",
        )}`,
      );
    }
    // Sends the magic link via Brevo + redirects to /signin?check=1.
    await signIn("email", { email: result.email!, redirectTo: "/app" });
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <Link href="/" aria-label="sivra home" className="mb-10 inline-block">
        <Wordmark className="h-8" />
      </Link>

      {!valid ? (
        <div>
          <h1 className="text-3xl font-semibold">Link expired</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink/65">
            This sign-up link is invalid or has already been used. If you already
            finished setting up, just sign in.
          </p>
          <Link href="/signin" className="btn-accent mt-6 inline-block">
            Sign in
          </Link>
        </div>
      ) : (
        <>
          <h1 className="text-3xl font-semibold">Finish setting up</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink/65">
            We took your order over the phone
            {v?.phone ? ` (${formatPhoneDisplay(v.phone)})` : ""}. Add an email and
            a name for your workspace and it'll be waiting for you inside.
          </p>

          {order ? (
            <div className="mt-6 rounded-xl border border-accent/20 bg-accent/[0.04] p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-accent">
                Your order
              </p>
              <p className="mt-1 font-display text-lg font-semibold">{order.title}</p>
              <p className="mt-0.5 text-sm text-ink/60">
                {order.status === "COMPLETED" && order.resultTitle
                  ? `Found: ${order.resultTitle}${
                      euros(order.resultPriceCents, order.currency)
                        ? ` · ${euros(order.resultPriceCents, order.currency)}`
                        : ""
                    }`
                  : `Status: ${order.status.toLowerCase()}`}
              </p>
            </div>
          ) : null}

          <form action={finishClaim} className="mt-7 space-y-4">
            <div>
              <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-ink/80">
                Email address
              </label>
              <input
                id="email"
                name="email"
                type="email"
                required
                autoComplete="email"
                placeholder="you@company.com"
                className="field"
              />
            </div>
            <div>
              <label htmlFor="orgName" className="mb-1.5 block text-sm font-medium text-ink/80">
                Workspace name
              </label>
              <input
                id="orgName"
                name="orgName"
                type="text"
                required
                placeholder="Acme GmbH"
                className="field"
              />
            </div>
            {searchParams.error ? (
              <p className="text-sm text-red-700">{searchParams.error}</p>
            ) : null}
            <button type="submit" className="btn-accent w-full">
              Create my account
            </button>
            <p className="text-center text-xs text-ink/45">
              We'll email you a magic link to sign in — no password.
            </p>
          </form>
        </>
      )}

      <p className="mt-10 text-sm text-ink/50">
        <Link href="/" className="hover:text-accent">
          ← Back home
        </Link>
      </p>
    </main>
  );
}
