/**
 * "Under the hood" — honest about the real architecture (RESEARCH-FLOW.md +
 * ARCHITECTURE.md). Hackathon judges want the substance, so it's confident and
 * specific: supervisor (Gemini 3.1 Pro) → overfit VLM fleet on Modal →
 * aggregated report → auto-buy or routed escalation → done, all audited.
 */

const steps = [
  {
    k: "01",
    title: "Intake",
    tag: "voice or chat",
    body: "An employee asks by phone (ElevenLabs ConvAI) or in the chat UI. sivra creates an org-scoped Order and starts the audit trail.",
  },
  {
    k: "02",
    title: "Supervisor plans",
    tag: "Gemini 3.1 Pro · Modal",
    body: "A supervisor agent reads the goal and budget, decides how many agents to spawn and where, and narrates progress to the audit trail as it goes.",
  },
  {
    k: "03",
    title: "The fleet shops",
    tag: "overfit VLMs · sandboxed",
    body: "N small, specialized vision models run in parallel on Modal sandboxes, each browsing one marketplace and pushing live tiles to Mission Control.",
  },
  {
    k: "04",
    title: "Aggregate to a report",
    tag: "ResearchReport",
    body: "The supervisor collects each agent's best candidate and synthesizes one comparison report: best option, price-vs-budget, alternatives, recommendation.",
  },
  {
    k: "05",
    title: "Decide",
    tag: "auto-buy or route",
    body: "In budget and the requester is authorized? Auto-buy, no human. Otherwise build a DecisionRequest, ask the learned router who signs off, and dispatch.",
  },
  {
    k: "06",
    title: "Resolve & retrain",
    tag: "Pioneer · continual",
    body: "Approve, counter (re-research with a refined goal), or decline. Every resolution becomes training signal — the router retrains on Pioneer.",
  },
];

export function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-20">
      <div className="mx-auto max-w-6xl px-6 py-20 lg:py-28">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">
            Under the hood
          </p>
          <h2 className="mt-4 text-balance text-4xl font-semibold leading-[1.1] sm:text-5xl">
            How a request becomes a receipt.
          </h2>
          <p className="mt-6 text-lg leading-relaxed text-ink/70">
            No black box. A supervisor agent orchestrates the fleet, aggregates
            an answer, and hands a clean decision to a router that keeps getting
            better. Every step writes an append-only audit row.
          </p>
        </div>

        {/* horizontal flow strip */}
        <FlowStrip />

        {/* the six steps */}
        <div className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-ink/10 bg-ink/10 sm:grid-cols-2 lg:grid-cols-3">
          {steps.map((s) => (
            <div key={s.k} className="flex flex-col bg-paper p-6 lg:p-7">
              <div className="flex items-center justify-between">
                <span className="font-display text-2xl font-semibold text-accent/70">
                  {s.k}
                </span>
                <span className="rounded-full border border-ink/15 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.1em] text-ink/55">
                  {s.tag}
                </span>
              </div>
              <h3 className="mt-4 text-lg font-semibold">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink/65">
                {s.body}
              </p>
            </div>
          ))}
        </div>

        {/* the seam callout */}
        <div className="mt-10 rounded-2xl border border-accent/20 bg-accent/[0.04] p-7 lg:p-8">
          <p className="max-w-3xl text-sm leading-relaxed text-ink/70">
            Research and the decision are deliberately separate stages, joined
            by one JSON seam &mdash; the <strong>ResearchReport</strong>. The
            fleet&apos;s job ends when it posts the report; the app&apos;s job
            is to act on it. Clean contract, fully replayable.
          </p>
        </div>
      </div>
    </section>
  );
}

function FlowStrip() {
  const nodes = [
    "request",
    "supervisor",
    "VLM fleet",
    "report",
    "approve / auto-buy",
    "done",
  ];
  return (
    <div className="mt-12 flex flex-wrap items-center gap-x-2 gap-y-3">
      {nodes.map((n, i) => (
        <div key={n} className="flex items-center gap-2">
          <span
            className={`rounded-full px-3.5 py-1.5 text-sm font-medium ${
              i === 0 || i === nodes.length - 1
                ? "bg-accent text-paper"
                : "border border-ink/15 bg-white/60 text-ink/80"
            }`}
          >
            {n}
          </span>
          {i < nodes.length - 1 && (
            <span aria-hidden className="text-ink/30">
              &rarr;
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
