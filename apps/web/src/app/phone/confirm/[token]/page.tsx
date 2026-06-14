import Link from "next/link";
import { confirmPhone } from "@/lib/phone-link";
import { Wordmark } from "@/app/_components/Wordmark";

// /phone/confirm/:token — opened from the SMS we text a signed-in user who added
// a phone. Receiving the link proves they hold the number, so we confirm on load.
export const dynamic = "force-dynamic";

export default async function ConfirmPhonePage({
  params,
}: {
  params: { token: string };
}) {
  const result = await confirmPhone(params.token);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <Link href="/" aria-label="sivra home" className="mb-10 inline-block">
        <Wordmark className="h-8" />
      </Link>

      {result.ok ? (
        <div>
          <div className="mb-4 inline-flex size-11 items-center justify-center rounded-full bg-emerald-600/15 text-2xl text-emerald-700">
            ✓
          </div>
          <h1 className="text-3xl font-semibold">Number confirmed</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink/65">
            Your phone is now linked to your sivra account. Calls from it place
            orders in your workspace, and any approvals will reach you here.
          </p>
          <Link href="/app" className="btn-accent mt-6 inline-block">
            Go to sivra
          </Link>
        </div>
      ) : (
        <div>
          <h1 className="text-3xl font-semibold">Couldn't confirm</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink/65">{result.error}</p>
          <Link href="/app" className="btn-accent mt-6 inline-block">
            Back to sivra
          </Link>
        </div>
      )}
    </main>
  );
}
