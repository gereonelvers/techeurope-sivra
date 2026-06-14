import Link from "next/link";
import { redirect } from "next/navigation";
import { auth, signIn } from "@/lib/auth";
import { Wordmark } from "@/app/_components/Wordmark";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: { check?: string; error?: string };
}) {
  const session = await auth();
  if (session?.user) redirect("/app");

  const checkInbox = searchParams.check === "1";

  // Server action — kicks off the Auth.js email (magic-link) flow, which
  // delivers via Brevo (see src/lib/auth.ts sendVerificationRequest).
  async function startSignIn(formData: FormData) {
    "use server";
    const email = String(formData.get("email") ?? "").trim();
    if (!email) return;
    await signIn("email", { email, redirectTo: "/app" });
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <Link href="/" aria-label="sivra home" className="mb-10 inline-block">
        <Wordmark className="h-8" />
      </Link>

      <h1 className="text-3xl font-semibold">Sign in</h1>
      <p className="mt-2 text-sm leading-relaxed text-ink/65">
        Enter your email and we'll send you a magic link. No password needed.
      </p>

      {checkInbox ? (
        <div className="mt-8 rounded-xl border border-accent/25 bg-accent/5 p-5 text-sm leading-relaxed text-ink/80">
          <p className="font-semibold text-ink">Check your inbox</p>
          <p className="mt-1">
            We sent you a sign-in link. It expires in 24 hours. You can close this
            tab.
          </p>
        </div>
      ) : (
        <form action={startSignIn} className="mt-8 space-y-4">
          <div>
            <label
              htmlFor="email"
              className="mb-1.5 block text-sm font-medium text-ink/80"
            >
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
          {searchParams.error ? (
            <p className="text-sm text-red-700">
              Something went wrong. Please try again.
            </p>
          ) : null}
          <button type="submit" className="btn-accent w-full">
            Send magic link
          </button>
        </form>
      )}

      <p className="mt-10 text-sm text-ink/50">
        <Link href="/" className="hover:text-accent">
          ← Back home
        </Link>
      </p>
    </main>
  );
}
