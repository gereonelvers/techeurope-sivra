/**
 * USP 2 — the learning router. Lead with the insight (it discovers the real
 * delegation graph), mechanism as supporting detail. Right rail: a small
 * "priors → feedback → learned" visual.
 */
export function RouterUSP() {
  return (
    <section id="router" className="scroll-mt-20 border-y border-ink/10 bg-white/40">
      <div className="mx-auto max-w-6xl px-6 py-20 lg:py-28">
        <div className="grid items-center gap-14 lg:grid-cols-[1fr_1fr]">
          <RouterDiagram />

          <div className="lg:order-first">
            <h2 className="text-balance text-4xl font-semibold leading-[1.1] sm:text-5xl">
              It learns who actually signs off.
            </h2>
            <p className="mt-6 text-lg leading-relaxed text-ink/70">
              Every company&apos;s documented approval matrix is wrong. Who
              really decides is tribal knowledge &mdash; the manager who&apos;s
              technically the approver but always defers to the lead engineer,
              the budget owner who&apos;s been on leave for a month.
            </p>
            <p className="mt-5 text-lg leading-relaxed text-ink/70">
              sivra starts from sensible priors &mdash; org chart, spend limits,
              category ownership &mdash; and{" "}
              <span className="text-ink">
                adapts from every &ldquo;not me, talk to X.&rdquo;
              </span>{" "}
              Over time it discovers the real delegation graph: the routing your
              org runs on, not the one in the handbook.
            </p>

            <ul className="mt-8 space-y-3.5">
              <Bullet>
                Priors from org chart, approval limits and category ownership
              </Bullet>
              <Bullet>
                Each resolution is feedback &mdash; corrected role, corrected
                urgency, &ldquo;route to someone else&rdquo;
              </Bullet>
              <Bullet>
                The router is fine-tuned and continually retrained on Pioneer,
                so the next request routes smarter
              </Bullet>
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

function Bullet({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-3 text-base leading-relaxed text-ink/75">
      <span className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
      {children}
    </li>
  );
}

function RouterDiagram() {
  return (
    <div className="relative">
      <div className="absolute -inset-3 -z-10 rounded-[28px] bg-accent/5 blur-2xl" />
      <div className="overflow-hidden rounded-2xl border border-ink/10 bg-white/70 p-6 shadow-[0_24px_60px_-30px_rgba(33,31,26,0.4)] backdrop-blur lg:p-7">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink/45">
          Documented matrix
        </p>
        <div className="mt-2 rounded-lg border border-dashed border-ink/20 bg-paper/60 px-4 py-2.5 text-sm text-ink/45 line-through decoration-ink/30">
          &euro;500&ndash;5k &rarr; Dept. Manager
        </div>

        <div className="my-3 flex items-center gap-3 text-xs text-ink/40">
          <span className="h-px flex-1 bg-ink/10" />
          feedback over time
          <span className="h-px flex-1 bg-ink/10" />
        </div>

        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          Learned delegation graph
        </p>
        <div className="mt-2 space-y-2">
          <FeedbackRow
            from="Dept. Manager"
            note="&ldquo;not me &mdash; ask the lead eng&rdquo;"
          />
          <FeedbackRow
            from="Lead Engineer"
            note="approves &middot; 9 of 9 in-category"
            resolved
          />
        </div>

        <div className="mt-4 rounded-lg border border-accent/25 bg-accent/[0.05] px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-accent">
            Now routes
          </p>
          <p className="mt-1 text-sm font-medium text-ink/85">
            Tools &amp; equipment, &euro;500&ndash;5k &rarr; Lead Engineer
          </p>
          <p className="mt-0.5 text-xs text-ink/50">
            model v7 &middot; retrained from 41 resolved requests
          </p>
        </div>
      </div>
    </div>
  );
}

function FeedbackRow({
  from,
  note,
  resolved,
}: {
  from: string;
  note: string;
  resolved?: boolean;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-ink/10 bg-paper/60 px-4 py-2.5">
      <span className="text-sm font-medium text-ink/80">{from}</span>
      <span
        className={`text-xs ${resolved ? "text-accent" : "text-ink/55"}`}
        dangerouslySetInnerHTML={{ __html: note }}
      />
    </div>
  );
}
