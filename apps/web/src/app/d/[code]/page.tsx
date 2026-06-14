import { prisma } from "@/lib/db";
import { formatCents } from "@/lib/orders";
import { ReplyForm } from "./ReplyForm";

// Public tokenized reply page. The unguessable `code` is the capability — no
// session required. Replaces the old supervisor /d/{code}. Renders the decision
// + an approve/counter/decline + 👍/🤷/👎 feedback form; the form POSTs to
// /api/d/:code which calls resolveEscalation().
export const dynamic = "force-dynamic";

export default async function ReplyPage({
  params,
}: {
  params: { code: string };
}) {
  const escalation = await prisma.escalation.findUnique({
    where: { code: params.code },
    include: {
      order: { select: { title: true, brand: true, category: true, currency: true } },
      org: { select: { name: true } },
      targetMembership: {
        select: { user: { select: { name: true, email: true } } },
      },
    },
  });

  if (!escalation) {
    return (
      <Shell>
        <h1 className="font-display text-2xl font-semibold">Link not found</h1>
        <p className="mt-3 text-sm text-ink/60">
          This reply link is invalid or has expired.
        </p>
      </Shell>
    );
  }

  const resolved = escalation.status === "RESOLVED";
  const proposed = escalation.proposedValueCents;
  const cap = escalation.budgetCapCents;
  const currency = escalation.order?.currency ?? "EUR";

  return (
    <Shell>
      <p className="text-xs font-semibold uppercase tracking-wider text-accent">
        {escalation.org.name} · approval request
      </p>
      <h1 className="mt-2 font-display text-2xl font-semibold leading-tight">
        {escalation.order?.title ?? "A purchase needs your sign-off"}
      </h1>

      <p className="mt-4 text-[15px] leading-relaxed text-ink/80">
        {escalation.suggestedMessage || escalation.situationText}
      </p>

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 rounded-xl border border-ink/10 bg-white/60 p-5 text-sm">
        {escalation.order?.brand ? (
          <Field label="Brand" value={escalation.order.brand} />
        ) : null}
        {escalation.order?.category ? (
          <Field label="Category" value={escalation.order.category} />
        ) : null}
        <Field
          label="Proposed price"
          value={formatCents(proposed, currency)}
          emphasize
        />
        <Field label="Budget cap" value={formatCents(cap, currency)} />
        <Field
          label="Urgency"
          value={escalation.urgencyTier.toLowerCase().replace("_", " ")}
        />
        {escalation.targetPurchasingRole ? (
          <Field label="Routed to" value={escalation.targetPurchasingRole} />
        ) : null}
      </dl>

      {resolved ? (
        <div className="mt-7 rounded-xl border border-ink/10 bg-white/60 p-5">
          <p className="text-sm font-semibold">
            Already resolved: {escalation.resolution}
          </p>
          {escalation.resolvedValueCents != null ? (
            <p className="mt-1 text-sm text-ink/60">
              at {formatCents(escalation.resolvedValueCents, currency)}
            </p>
          ) : null}
          <p className="mt-2 text-xs text-ink/50">
            Thank you — no further action is needed.
          </p>
        </div>
      ) : (
        <ReplyForm
          code={params.code}
          defaultValueCents={proposed ?? cap ?? null}
        />
      )}

      <p className="mt-8 text-center text-xs text-ink/40">
        sivra · this link is unique to this request
      </p>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-paper px-5 py-12">
      <div className="mx-auto max-w-lg rounded-2xl border border-ink/10 bg-white/40 p-7 shadow-sm sm:p-9">
        {children}
      </div>
    </main>
  );
}

function Field({
  label,
  value,
  emphasize,
}: {
  label: string;
  value: string;
  emphasize?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink/45">{label}</dt>
      <dd
        className={
          emphasize
            ? "mt-0.5 font-display text-lg font-semibold"
            : "mt-0.5 text-sm font-medium capitalize"
        }
      >
        {value}
      </dd>
    </div>
  );
}
