/**
 * USP — the VLM fleet as a discovery/sourcing engine. Strongest, most
 * demoable. Left: the argument + parallelism punchline. Right: a mission-
 * control wall of many small browsing agents working in parallel.
 */
export function FleetUSP() {
  return (
    <section id="fleet" className="scroll-mt-20">
      <div className="mx-auto max-w-6xl px-6 py-20 lg:py-28">
        <div className="grid items-start gap-14 lg:grid-cols-[1fr_1fr]">
          <div>
            <h2 className="text-balance text-4xl font-semibold leading-[1.1] sm:text-5xl">
              A swarm of small agents, not one big browser.
            </h2>
            <p className="mt-6 text-lg leading-relaxed text-ink/70">
              sivra dispatches many small, specialized vision agents into open
              marketplaces <span className="text-ink">in parallel</span> &mdash;
              each cheap enough to spawn on demand, reaching well past the
              suppliers you&apos;ve already onboarded.
            </p>

            <p className="mt-5 text-lg leading-relaxed text-ink/70">
              That&apos;s breadth and speed a single large browsing agent
              can&apos;t match: a hundred narrow agents shopping a hundred sites
              at once beat one generalist clicking through them in sequence.
            </p>

            <div className="mt-8 grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-ink/10 bg-ink/10">
              <Stat n="3" label="Small — quick look" />
              <Stat n="12" label="Medium — broad sweep" />
              <Stat n="100" label="Deep — full market" />
            </div>
            <p className="mt-3 text-sm leading-relaxed text-ink/45">
              Up to 100 agents per search &mdash; the supervisor sizes the fleet
              to the request.
            </p>

            <p className="mt-8 text-base leading-relaxed text-ink/55">
              Each agent pushes live tiles as it browses; the supervisor watches
              all of them and collapses the run into one answer. The artifact
              you get back isn&apos;t a list of tabs &mdash; it&apos;s a
              decision.
            </p>
          </div>

          <AgentWall />
        </div>
      </div>
    </section>
  );
}

function Stat({ n, label }: { n: string; label: string }) {
  return (
    <div className="bg-paper px-4 py-5 text-center">
      <p className="font-display text-3xl font-semibold text-accent">{n}</p>
      <p className="mt-1 text-xs leading-tight text-ink/55">{label}</p>
    </div>
  );
}

/**
 * Mission-control wall: a grid of small browsing-agent tiles, each a tiny
 * "browser" with a marketplace label, a couple of skeleton result rows, and a
 * status dot. Reads as "many agents browsing in parallel." Pure divs/SVG, on
 * palette, no real images.
 */
function AgentWall() {
  // A spread of marketplace-ish labels + statuses for the visible tiles.
  const tiles: { site: string; status: AgentStatus; hit?: boolean }[] = [
    { site: "BidBay", status: "found", hit: true },
    { site: "MarktX", status: "browsing" },
    { site: "ToolHaus", status: "browsing" },
    { site: "Regio-7", status: "found" },
    { site: "PartsLane", status: "browsing" },
    { site: "OpenBazaar", status: "queued" },
    { site: "Liefr", status: "browsing" },
    { site: "GearPit", status: "found" },
    { site: "Stockwell", status: "browsing" },
  ];

  return (
    <div className="relative">
      <div className="absolute -inset-3 -z-10 rounded-[28px] bg-accent/5 blur-2xl" />
      <div className="overflow-hidden rounded-2xl border border-ink/10 bg-white/70 shadow-[0_24px_60px_-30px_rgba(33,31,26,0.4)] backdrop-blur">
        <div className="flex items-center justify-between border-b border-ink/10 px-5 py-3.5">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-ink/15" />
            <span className="h-2.5 w-2.5 rounded-full bg-ink/15" />
            <span className="h-2.5 w-2.5 rounded-full bg-ink/15" />
            <span className="ml-2 text-xs font-medium tracking-wide text-ink/45">
              Mission Control &middot; live
            </span>
          </div>
          <span className="rounded-full bg-accent/10 px-2.5 py-1 text-[11px] font-semibold text-accent">
            100 agents &middot; Deep
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2.5 p-4">
          {tiles.map((t, i) => (
            <AgentTile key={`${t.site}-${i}`} {...t} />
          ))}
        </div>

        <div className="flex items-center justify-between border-t border-ink/10 px-5 py-3 text-[11px] font-medium text-ink/45">
          <span>+91 more agents browsing&hellip;</span>
          <span className="text-accent">12 candidates so far</span>
        </div>
      </div>
    </div>
  );
}

type AgentStatus = "browsing" | "found" | "queued";

const STATUS_META: Record<AgentStatus, { label: string; dot: string; text: string }> = {
  browsing: { label: "browsing", dot: "bg-accent animate-pulse", text: "text-ink/45" },
  found: { label: "found", dot: "bg-accent", text: "text-accent" },
  queued: { label: "queued", dot: "bg-ink/25", text: "text-ink/35" },
};

function AgentTile({
  site,
  status,
  hit,
}: {
  site: string;
  status: AgentStatus;
  hit?: boolean;
}) {
  const meta = STATUS_META[status];
  return (
    <div
      className={`overflow-hidden rounded-lg border bg-white/80 ${
        hit ? "border-accent/30" : "border-ink/10"
      }`}
    >
      {/* tiny browser chrome */}
      <div className="flex items-center gap-1.5 border-b border-ink/[0.07] px-2 py-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-ink/15" />
        <span className="truncate text-[9px] font-medium text-ink/50">{site}</span>
      </div>
      {/* skeleton "page" */}
      <div className="space-y-1.5 px-2 py-2">
        <div className="flex gap-1.5">
          <div
            className={`h-5 w-5 shrink-0 rounded ${
              hit ? "bg-accent/20" : "bg-ink/[0.06]"
            }`}
          />
          <div className="flex-1 space-y-1 pt-0.5">
            <div
              className={`h-1.5 rounded-full ${
                hit ? "w-4/5 bg-accent/25" : "w-3/4 bg-ink/[0.08]"
              }`}
            />
            <div className="h-1.5 w-1/2 rounded-full bg-ink/[0.06]" />
          </div>
        </div>
        <div className="h-1.5 w-2/3 rounded-full bg-ink/[0.06]" />
      </div>
      {/* status footer */}
      <div className="flex items-center gap-1.5 px-2 pb-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
        <span className={`text-[9px] font-medium ${meta.text}`}>{meta.label}</span>
      </div>
    </div>
  );
}
