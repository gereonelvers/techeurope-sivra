/** The three reframed cards. No table-stakes copy — these are the wedge. */

const cards = [
  {
    eyebrow: "Sourcing",
    title: "Shops the open market",
    body: "A fleet of vision agents finds real options beyond your catalog — marketplaces with no API, regional sellers, live in-session pricing. Not just the suppliers you’ve already onboarded.",
  },
  {
    eyebrow: "Routing",
    title: "Learns who really approves",
    body: "Your documented approval matrix is wrong. sivra routes sign-off to how your org actually decides, and adapts every time someone says “not me — talk to X.”",
  },
  {
    eyebrow: "Learning",
    title: "Gets sharper with every order",
    body: "Every resolved request is a reward signal. The fleet and the delegation router retrain continually — Pioneer fine-tunes the routing, the Modal-sandboxed agents learn the marketplaces — so each search and each sign-off lands closer than the last.",
  },
];

export function ValueCards() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-16 lg:py-20">
      <div className="grid gap-px overflow-hidden rounded-2xl border border-ink/10 bg-ink/10 sm:grid-cols-3">
        {cards.map((c) => (
          <div
            key={c.title}
            className="group flex flex-col bg-paper p-7 transition-colors hover:bg-white/60 lg:p-8"
          >
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">
              {c.eyebrow}
            </p>
            <h3 className="mt-3 text-xl font-semibold leading-tight">
              {c.title}
            </h3>
            <p className="mt-3 text-sm leading-relaxed text-ink/65">{c.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
