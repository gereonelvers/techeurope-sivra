"use client";

import { useState } from "react";

type Resolution = "approve" | "counter" | "decline";
type Rating = "good" | "partial" | "wrong";

interface Escalation {
  code: string;
  decisionType: string;
  situationText: string;
  suggestedMessage: string | null;
  proposedValueCents: number | null;
  budgetCapCents: number | null;
  urgencyTier: string;
  targetPurchasingRole: string | null;
}

const euros = (cents: number | null | undefined, currency = "EUR") => {
  if (cents == null) return "—";
  try {
    return new Intl.NumberFormat("en-IE", {
      style: "currency",
      currency: currency || "EUR",
    }).format(cents / 100);
  } catch {
    return `€${(cents / 100).toFixed(2)}`;
  }
};

// In-app approver: an inline approve/counter/decline + 👍🤷👎 control shown on
// the order detail page when the viewer may resolve a PENDING escalation. POSTs
// to /api/d/:code (the shared resolve path). On success the parent re-polls.
export function InlineApprover({
  escalation,
  currency,
  onResolved,
}: {
  escalation: Escalation;
  currency: string;
  onResolved: () => void;
}) {
  const [resolution, setResolution] = useState<Resolution | null>(null);
  const [rating, setRating] = useState<Rating | null>(null);
  const [counterEuros, setCounterEuros] = useState(
    escalation.proposedValueCents != null
      ? (escalation.proposedValueCents / 100).toString()
      : "",
  );
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!resolution) {
      setError("Pick approve, counter, or decline.");
      return;
    }
    setBusy(true);
    setError(null);
    const value =
      resolution === "counter" && counterEuros.trim()
        ? Math.round(parseFloat(counterEuros.replace(",", ".")) * 100)
        : resolution === "approve"
          ? escalation.proposedValueCents
          : null;
    try {
      const res = await fetch(`/api/d/${escalation.code}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resolution,
          value,
          notes: notes.trim() || null,
          rating,
          resolvedByLabel: "in-app approver",
        }),
      });
      if (res.ok) {
        onResolved();
      } else {
        const data = await res.json().catch(() => ({}));
        setError(data.error ?? "Could not submit.");
        setBusy(false);
      }
    } catch {
      setError("Network error — try again.");
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 rounded-xl border border-accent/25 bg-accent/5 p-5">
      <p className="text-xs font-semibold uppercase tracking-wide text-accent">
        Needs your sign-off ·{" "}
        {(escalation.urgencyTier ?? "").toLowerCase().replace("_", " ")}
      </p>
      <p className="mt-1.5 text-sm text-ink/80">
        {escalation.suggestedMessage || escalation.situationText}
      </p>
      <p className="mt-1 text-xs text-ink/50">
        proposed {euros(escalation.proposedValueCents, currency)} · cap{" "}
        {euros(escalation.budgetCapCents, currency)}
      </p>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <Choice label="Approve" tone="approve" active={resolution === "approve"} onClick={() => setResolution("approve")} />
        <Choice label="Counter" tone="counter" active={resolution === "counter"} onClick={() => setResolution("counter")} />
        <Choice label="Decline" tone="decline" active={resolution === "decline"} onClick={() => setResolution("decline")} />
      </div>

      {resolution === "counter" ? (
        <label className="mt-3 block">
          <span className="text-xs uppercase tracking-wide text-ink/45">
            Counter offer ({currency})
          </span>
          <input
            value={counterEuros}
            onChange={(e) => setCounterEuros(e.target.value)}
            inputMode="decimal"
            className="field mt-1"
          />
        </label>
      ) : null}

      <label className="mt-3 block">
        <span className="text-xs uppercase tracking-wide text-ink/45">Notes (optional)</span>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="field mt-1 resize-none"
          placeholder="Context for the buyer agent…"
        />
      </label>

      <div className="mt-3">
        <span className="text-xs uppercase tracking-wide text-ink/45">
          Right person & urgency?
        </span>
        <div className="mt-2 flex gap-2">
          <Feedback emoji="👍" label="good" active={rating === "good"} onClick={() => setRating("good")} />
          <Feedback emoji="🤷" label="partial" active={rating === "partial"} onClick={() => setRating("partial")} />
          <Feedback emoji="👎" label="wrong" active={rating === "wrong"} onClick={() => setRating("wrong")} />
        </div>
      </div>

      {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}

      <button
        type="button"
        onClick={submit}
        disabled={busy || !resolution}
        className="btn-accent mt-4 w-full"
      >
        {busy ? "Submitting…" : "Submit decision"}
      </button>
    </div>
  );
}

function Choice({
  label,
  tone,
  active,
  onClick,
}: {
  label: string;
  tone: "approve" | "counter" | "decline";
  active: boolean;
  onClick: () => void;
}) {
  const toneActive =
    tone === "approve"
      ? "border-emerald-600 bg-emerald-600 text-white"
      : tone === "decline"
        ? "border-red-600 bg-red-600 text-white"
        : "border-accent bg-accent text-white";
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-lg border px-3 py-2.5 text-sm font-semibold transition",
        active ? toneActive : "border-ink/15 bg-white/70 text-ink/70 hover:border-ink/30",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

function Feedback({
  emoji,
  label,
  active,
  onClick,
}: {
  emoji: string;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={[
        "flex-1 rounded-lg border px-3 py-2 text-lg transition",
        active ? "border-accent bg-accent/15" : "border-ink/15 bg-white/70 hover:border-ink/30",
      ].join(" ")}
    >
      {emoji}
    </button>
  );
}
