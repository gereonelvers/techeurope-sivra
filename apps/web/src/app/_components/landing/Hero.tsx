import Link from "next/link";

/**
 * Hero — leads with the wedge: sivra handles the spend you *haven't*
 * structured. The right rail is a single, prominent hand-built long-tail
 * (Zipf) curve — the positioning, drawn — rendered straight onto the page
 * background with no card chrome.
 */
export function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* soft accent wash behind the hero */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(60% 50% at 78% 8%, rgba(58,53,124,0.10), transparent 70%)",
        }}
      />
      <div className="mx-auto grid max-w-6xl items-center gap-14 px-6 pb-20 pt-16 lg:grid-cols-[1fr_1.1fr] lg:pb-28 lg:pt-24">
        <div>
          <h1 className="max-w-2xl text-balance text-5xl font-semibold leading-[1.05] sm:text-6xl">
            The purchases your procurement stack never sees.
          </h1>
          <p className="mt-7 max-w-xl text-lg leading-relaxed text-ink/70">
            <span className="text-ink">sivra takes the spend you never
            structured</span> &mdash; one-off buys, new-supplier hunts, the
            messy long tail. An employee asks by phone or chat, and a fleet of
            agents shops the open market and figures out who needs to approve.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-4">
            <Link href="/signin" className="btn-accent">
              Get started
            </Link>
            {/* Fun "Call Sivra" CTA — your (very busy) procurement employee. */}
            <a
              href="tel:+14472154920"
              className="group inline-flex items-center gap-2.5 rounded-full border border-ink/15 bg-white/60 py-1 pl-1 pr-4 transition hover:border-accent/40"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/sivra-person.png"
                alt="Sivra, your procurement employee"
                className="size-10 rounded-full object-cover ring-1 ring-ink/10"
                style={{ objectPosition: "50% 22%" }}
              />
              <span className="flex flex-col leading-tight">
                <span className="flex items-center gap-1.5 text-sm font-semibold text-ink/85 transition group-hover:text-accent">
                  <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z" />
                  </svg>
                  Call Sivra
                </span>
                <span className="text-xs tabular-nums text-ink/50">+1 447 215 4920</span>
              </span>
            </a>
          </div>
          <a
            href="#how"
            className="mt-4 inline-block text-sm font-medium text-ink/55 underline-offset-4 transition hover:text-ink hover:underline"
          >
            See how it works &darr;
          </a>
        </div>

        <LongTailCurve />
      </div>
    </section>
  );
}

/**
 * The positioning, drawn: a Zipfian long-tail distribution. The steep head is
 * shaded faint/muted (what the procurement stack already covers); the long
 * flat tail is rendered in the accent color and called out as the spend sivra
 * handles. Hand-built inline SVG — no libraries, no card chrome, tuned to read
 * directly on the page background.
 */
function LongTailCurve() {
  // ViewBox geometry. Bars run left (high head) to right (long tail).
  const W = 560;
  const H = 360;
  const baseY = 286; // x-axis baseline
  const left = 28;
  const right = 540;

  // The split between the structured "head" and the long "tail".
  const splitX = 210;

  // A smooth Zipf-ish curve: tall on the left, decaying into a long low tail.
  const headPath =
    "M28 56 C 78 60, 110 142, 150 200 S 192 262, 210 272";
  const tailPath =
    "M210 272 C 258 282, 330 290, 400 292 S 500 294, 540 294";

  // Area-fill variants (down to the baseline) for the soft washes.
  const headArea = `${headPath} L210 ${baseY} L28 ${baseY} Z`;
  const tailArea = `${tailPath} L540 ${baseY} L210 ${baseY} Z`;

  return (
    <figure className="relative -mt-2 lg:mt-0">
      <figcaption className="mb-2 flex items-baseline justify-between px-1">
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink/45">
          Purchase volume
        </span>
        <span className="text-[11px] font-medium text-ink/40">
          by spend category
        </span>
      </figcaption>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full overflow-visible"
        role="img"
        aria-label="A long-tail (Zipf) distribution of company spend: a steep, faint head that the existing procurement stack already covers, dropping into a long accent-colored tail that sivra handles."
      >
        <defs>
          <linearGradient id="lt-head" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#211f1a" stopOpacity="0.12" />
            <stop offset="100%" stopColor="#211f1a" stopOpacity="0.01" />
          </linearGradient>
          <linearGradient id="lt-tail" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3A357C" stopOpacity="0.26" />
            <stop offset="100%" stopColor="#3A357C" stopOpacity="0.04" />
          </linearGradient>
        </defs>

        {/* baseline */}
        <line
          x1={left}
          y1={baseY}
          x2={right}
          y2={baseY}
          stroke="#211f1a"
          strokeOpacity="0.18"
          strokeWidth="1.25"
        />

        {/* dashed split between structured head and the long tail */}
        <line
          x1={splitX}
          y1="44"
          x2={splitX}
          y2={baseY}
          stroke="#3A357C"
          strokeOpacity="0.32"
          strokeWidth="1.25"
          strokeDasharray="3 4"
        />

        {/* area fills */}
        <path d={headArea} fill="url(#lt-head)" />
        <path d={tailArea} fill="url(#lt-tail)" />

        {/* the curve itself — muted head, accent tail */}
        <path
          d={headPath}
          fill="none"
          stroke="#211f1a"
          strokeOpacity="0.38"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <path
          d={tailPath}
          fill="none"
          stroke="#3A357C"
          strokeWidth="3.5"
          strokeLinecap="round"
        />

        {/* endpoint dot on the tail */}
        <circle cx="540" cy="294" r="4" fill="#3A357C" />

        {/* head label */}
        <text
          x="42"
          y="92"
          fill="#211f1a"
          fillOpacity="0.5"
          fontSize="13"
          fontWeight="600"
        >
          <tspan x="42" dy="0">
            What your stack
          </tspan>
          <tspan x="42" dy="16">
            already covers
          </tspan>
        </text>

        {/* tail callout — connector + label */}
        <line
          x1="408"
          y1="292"
          x2="408"
          y2="222"
          stroke="#3A357C"
          strokeOpacity="0.5"
          strokeWidth="1.25"
        />
        <circle cx="408" cy="292" r="3.5" fill="#3A357C" />
        <text
          x="408"
          y="210"
          textAnchor="middle"
          fill="#3A357C"
          fontSize="14"
          fontWeight="700"
        >
          the tail sivra handles
        </text>
      </svg>
    </figure>
  );
}
