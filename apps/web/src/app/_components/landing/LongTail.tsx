/**
 * The wedge, spelled out: structured spend vs. the long tail. A simple
 * two-column contrast — incumbents on the left, the gap sivra owns on the right.
 */
export function LongTail() {
  return (
    <section className="border-y border-ink/10 bg-white/40">
      <div className="mx-auto max-w-6xl px-6 py-20 lg:py-28">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">
          The wedge
        </p>
        <h2 className="mt-4 max-w-3xl text-balance text-4xl font-semibold leading-[1.1] sm:text-5xl">
          The long tail you can&apos;t structure.
        </h2>
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink/70">
          Strategic-procurement tools like Tacto and Lio make the spend
          you&apos;ve already organized cheaper and cleaner. But you can only
          optimize what you&apos;ve structured &mdash; and most of what a
          company buys was never structured at all.
        </p>

        <div className="mt-12 grid gap-6 lg:grid-cols-2">
          <ContrastCard
            tone="muted"
            label="Already structured"
            sub="What incumbents optimize"
            items={[
              "Onboarded suppliers & framework agreements",
              "ERP line items and PO templates",
              "Negotiated catalogs, known prices",
              "Recurring, high-value, planned spend",
            ]}
          />
          <ContrastCard
            tone="accent"
            label="Not yet structured"
            sub="What sivra handles"
            items={[
              "Tail spend & one-off, ad-hoc buys",
              "New-supplier discovery on the open market",
              "No catalog, no API, live in-session pricing",
              "Where employees go rogue — maverick & dark spend",
            ]}
          />
        </div>

        <p className="mt-10 max-w-2xl text-base leading-relaxed text-ink/55">
          When there&apos;s no process to route into, people improvise &mdash;
          a personal card, a random vendor, a Slack message that never becomes a
          record. sivra gives that spend a front door: go to the open market,
          find the options, figure out who needs to approve.
        </p>
      </div>
    </section>
  );
}

function ContrastCard({
  tone,
  label,
  sub,
  items,
}: {
  tone: "muted" | "accent";
  label: string;
  sub: string;
  items: string[];
}) {
  const accent = tone === "accent";
  return (
    <div
      className={`rounded-2xl border p-7 lg:p-8 ${
        accent
          ? "border-accent/25 bg-accent/[0.04]"
          : "border-ink/10 bg-paper"
      }`}
    >
      <div className="flex items-baseline justify-between gap-4">
        <h3
          className={`text-lg font-semibold ${
            accent ? "text-accent" : "text-ink/70"
          }`}
        >
          {label}
        </h3>
        <span className="text-xs uppercase tracking-[0.12em] text-ink/40">
          {sub}
        </span>
      </div>
      <ul className="mt-5 space-y-3">
        {items.map((it) => (
          <li
            key={it}
            className="flex items-start gap-3 text-sm leading-relaxed text-ink/75"
          >
            <span
              className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${
                accent ? "bg-accent" : "bg-ink/25"
              }`}
            />
            {it}
          </li>
        ))}
      </ul>
    </div>
  );
}
