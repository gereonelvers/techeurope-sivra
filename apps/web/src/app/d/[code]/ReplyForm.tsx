"use client";

import { useState } from "react";

type Resolution = "approve" | "counter" | "decline";
type Rating = "good" | "partial" | "wrong";

// The approve / counter / decline + 👍🤷👎 feedback control on the public reply
// page. POSTs to /api/d/:code which calls resolveEscalation().
export function ReplyForm({
  code,
  defaultValueCents,
}: {
  code: string;
  defaultValueCents: number | null;
}) {
  const [resolution, setResolution] = useState<Resolution | null>(null);
  const [rating, setRating] = useState<Rating | null>(null);
  const [counterEuros, setCounterEuros] = useState(
    defaultValueCents != null ? (defaultValueCents / 100).toString() : "",
  );
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
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
        : resolution === "approve" && defaultValueCents != null
          ? defaultValueCents
          : null;
    try {
      const res = await fetch(`/api/d/${code}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resolution,
          value,
          notes: notes.trim() || null,
          rating,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setDone(resolution);
      } else {
        setError(data.error ?? "Could not submit your reply.");
        setBusy(false);
      }
    } catch {
      setError("Network error — please try again.");
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="mt-7 rounded-xl border border-emerald-600/20 bg-emerald-50/60 p-5">
        <p className="text-sm font-semibold text-emerald-900">
          {done === "decline" ? "Declined." : done === "counter" ? "Counter sent." : "Approved."}
        </p>
        <p className="mt-1 text-xs text-emerald-800/70">
          Thank you — the buyer agent has been notified.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-7 space-y-5">
      <div className="grid grid-cols-3 gap-2">
        <Choice
          label="Approve"
          active={resolution === "approve"}
          tone="approve"
          onClick={() => setResolution("approve")}
        />
        <Choice
          label="Counter"
          active={resolution === "counter"}
          tone="counter"
          onClick={() => setResolution("counter")}
        />
        <Choice
          label="Decline"
          active={resolution === "decline"}
          tone="decline"
          onClick={() => setResolution("decline")}
        />
      </div>

      {resolution === "counter" ? (
        <label className="block">
          <span className="text-xs uppercase tracking-wide text-ink/45">
            Counter offer (EUR)
          </span>
          <input
            value={counterEuros}
            onChange={(e) => setCounterEuros(e.target.value)}
            inputMode="decimal"
            placeholder="e.g. 450"
            className="field mt-1"
          />
        </label>
      ) : null}

      <label className="block">
        <span className="text-xs uppercase tracking-wide text-ink/45">
          Notes (optional)
        </span>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder="Add context for the buyer agent…"
          className="field mt-1 resize-none"
        />
      </label>

      <div>
        <span className="text-xs uppercase tracking-wide text-ink/45">
          Was this routed to the right person?
        </span>
        <div className="mt-2 flex gap-2">
          <Feedback emoji="👍" label="good" active={rating === "good"} onClick={() => setRating("good")} />
          <Feedback emoji="🤷" label="partial" active={rating === "partial"} onClick={() => setRating("partial")} />
          <Feedback emoji="👎" label="wrong" active={rating === "wrong"} onClick={() => setRating("wrong")} />
        </div>
      </div>

      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <button
        type="button"
        onClick={submit}
        disabled={busy || !resolution}
        className="btn-accent w-full"
      >
        {busy ? "Submitting…" : "Submit reply"}
      </button>
    </div>
  );
}

function Choice({
  label,
  active,
  tone,
  onClick,
}: {
  label: string;
  active: boolean;
  tone: "approve" | "counter" | "decline";
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
        active ? toneActive : "border-ink/15 bg-white/60 text-ink/70 hover:border-ink/30",
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
        active ? "border-accent bg-accent/10" : "border-ink/15 bg-white/60 hover:border-ink/30",
      ].join(" ")}
    >
      {emoji}
    </button>
  );
}
