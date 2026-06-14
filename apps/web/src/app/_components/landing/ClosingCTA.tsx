import Link from "next/link";

/** Closing CTA + footer. */
export function ClosingCTA({ signedIn }: { signedIn: boolean }) {
  return (
    <>
      <section className="border-t border-ink/10">
        <div className="mx-auto max-w-6xl px-6 py-24 lg:py-32">
          <div className="relative overflow-hidden rounded-3xl border border-ink/10 bg-ink px-8 py-16 text-paper lg:px-16 lg:py-20">
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0"
              style={{
                background:
                  "radial-gradient(50% 60% at 85% 15%, rgba(58,53,124,0.55), transparent 70%)",
              }}
            />
            <div className="relative max-w-2xl">
              <h2 className="text-balance text-4xl font-semibold leading-[1.08] sm:text-5xl">
                Give your tail spend a front door.
              </h2>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-paper/70">
                Stop the maverick spend by making the right path the easy one.
                Ask sivra &mdash; the fleet shops the open market, the router
                finds the approver, and every purchase leaves a trail.
              </p>
              <div className="mt-9 flex flex-wrap items-center gap-x-5 gap-y-3">
                <Link
                  href={signedIn ? "/app" : "/signin"}
                  className="inline-flex items-center justify-center rounded-lg bg-paper px-6 py-3 text-sm font-semibold text-ink transition hover:opacity-90"
                >
                  {signedIn ? "Open dashboard" : "Get started"}
                </Link>
                <a
                  href="#fleet"
                  className="text-sm font-medium text-paper/70 underline-offset-4 transition hover:text-paper hover:underline"
                >
                  Revisit the fleet
                </a>
              </div>

              <div className="mt-10 flex flex-col gap-2 border-t border-paper/15 pt-7 sm:flex-row sm:items-center sm:gap-4">
                <span className="text-sm text-paper/55">
                  Or just call to place an order &mdash; talk to the voice agent:
                </span>
                <a
                  href="tel:+14472154920"
                  className="group inline-flex w-fit items-center gap-2.5 text-lg font-semibold text-paper transition hover:text-paper"
                >
                  <span
                    aria-hidden
                    className="flex h-9 w-9 items-center justify-center rounded-full bg-paper/10 ring-1 ring-paper/20 transition group-hover:bg-accent/40"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      className="h-4 w-4"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M6.5 3.5h3l1.2 3.6-1.8 1.3a12 12 0 0 0 5.4 5.4l1.3-1.8 3.6 1.2v3a1.5 1.5 0 0 1-1.6 1.5A15.5 15.5 0 0 1 5 5.1 1.5 1.5 0 0 1 6.5 3.5Z" />
                    </svg>
                  </span>
                  <span className="font-display tracking-tight underline-offset-4 group-hover:underline">
                    +1 447 215 4920
                  </span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>

      <footer className="border-t border-ink/10">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 px-6 py-10 text-sm text-ink/45 sm:flex-row sm:items-center">
          <span className="font-display text-lg font-semibold tracking-tight text-ink/70">
            sivra
          </span>
          <span>Tail-spend procurement, handled.</span>
          <span>&copy; {new Date().getFullYear()} sivra</span>
        </div>
      </footer>
    </>
  );
}
