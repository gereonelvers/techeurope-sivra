"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  FLEET_TIERS,
  FLEET_TIER_ORDER,
  type FleetTier,
} from "@/lib/fleet-tiers";

interface Extracted {
  title: string | null;
  category: string | null;
  brand: string | null;
  maxBudgetCents: number | null;
}

interface Turn {
  role: "user" | "assistant";
  content: string;
}

// The "nice agent UI": a chat where the user describes what to buy, an OpenAI
// assistant clarifies + extracts structured fields, and on confirmation we
// launch the order and route to its detail page. Every turn is persisted as a
// ChatMessage by /api/intake.
export function IntakeChat({
  defaultFleetTier,
}: {
  defaultFleetTier: FleetTier;
}) {
  const router = useRouter();
  const [tier, setTier] = useState<FleetTier>(defaultFleetTier);
  const [turns, setTurns] = useState<Turn[]>([
    {
      role: "assistant",
      content:
        "Hi — what would you like to buy? Describe the item, and a budget if you have one in mind.",
    },
  ]);
  const [input, setInput] = useState("");
  const [orderId, setOrderId] = useState<string | null>(null);
  const [extracted, setExtracted] = useState<Extracted | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, busy]);

  async function send() {
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setError(null);
    setTurns((t) => [...t, { role: "user", content: message }]);
    setBusy(true);
    try {
      const res = await fetch("/api/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ orderId, message }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error ?? "Something went wrong. Try again.");
        setBusy(false);
        return;
      }
      setOrderId(data.orderId);
      setExtracted(data.extracted ?? null);
      setReady(Boolean(data.ready));
      setTurns((t) => [...t, { role: "assistant", content: data.reply }]);
    } catch {
      setError("Network error — please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmAndLaunch() {
    if (!orderId || launching) return;
    setLaunching(true);
    setError(null);
    try {
      const res = await fetch(`/api/orders/${orderId}/launch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleetTier: tier }),
      });
      if (res.ok) {
        router.push(`/app/orders/${orderId}`);
      } else {
        const data = await res.json().catch(() => ({}));
        setError(data.error ?? "Could not launch the search.");
        setLaunching(false);
      }
    } catch {
      setError("Network error — please try again.");
      setLaunching(false);
    }
  }

  const euros = (cents: number | null | undefined) =>
    cents == null ? null : `€${(cents / 100).toFixed(cents % 100 === 0 ? 0 : 2)}`;

  return (
    <div className="mt-7 grid gap-5 lg:grid-cols-[1fr_260px]">
      {/* Chat column */}
      <div className="flex flex-col rounded-2xl border border-ink/10 bg-white/50">
        <div ref={scrollRef} className="max-h-[52vh] min-h-[280px] flex-1 space-y-3 overflow-y-auto p-5">
          {turns.map((t, i) => (
            <div
              key={i}
              className={t.role === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={[
                  "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
                  t.role === "user"
                    ? "bg-accent text-white"
                    : "bg-paper text-ink/85 border border-ink/10",
                ].join(" ")}
              >
                {t.content}
              </div>
            </div>
          ))}
          {busy ? (
            <div className="flex justify-start">
              <div className="rounded-2xl border border-ink/10 bg-paper px-4 py-2.5 text-sm text-ink/40">
                thinking…
              </div>
            </div>
          ) : null}
        </div>

        <div className="border-t border-ink/10 p-3">
          {error ? <p className="mb-2 px-2 text-sm text-red-700">{error}</p> : null}
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="e.g. An ergonomic office chair under €400"
              disabled={busy}
              className="field flex-1"
            />
            <button
              type="button"
              onClick={send}
              disabled={busy || !input.trim()}
              className="btn-accent shrink-0"
            >
              Send
            </button>
          </div>
        </div>
      </div>

      {/* Summary / confirm column */}
      <aside className="rounded-2xl border border-ink/10 bg-white/40 p-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">
          Draft order
        </p>
        <dl className="mt-3 space-y-2.5 text-sm">
          <Row label="Item" value={extracted?.title ?? "—"} />
          <Row label="Brand" value={extracted?.brand ?? "—"} />
          <Row label="Category" value={extracted?.category ?? "—"} />
          <Row label="Max budget" value={euros(extracted?.maxBudgetCents) ?? "—"} />
        </dl>

        {/* Fleet size for THIS search (defaults to the org setting) */}
        <div className="mt-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">
            Fleet size
          </p>
          <div className="mt-2 grid grid-cols-3 gap-1.5">
            {FLEET_TIER_ORDER.map((t) => {
              const meta = FLEET_TIERS[t];
              const selected = tier === t;
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTier(t)}
                  aria-pressed={selected}
                  title={meta.blurb}
                  className={[
                    "rounded-lg border px-2 py-1.5 text-center transition",
                    selected
                      ? "border-accent bg-accent/[0.08] ring-1 ring-accent/40"
                      : "border-ink/10 bg-white/60 hover:border-ink/25",
                  ].join(" ")}
                >
                  <span className="block text-xs font-semibold">{meta.label}</span>
                  <span className="block text-[10px] tabular-nums text-ink/45">
                    {meta.n}
                  </span>
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-[11px] text-ink/45">{FLEET_TIERS[tier].blurb}</p>
        </div>

        <button
          type="button"
          onClick={confirmAndLaunch}
          disabled={!ready || !orderId || launching}
          className="btn-accent mt-4 w-full"
        >
          {launching ? "Launching…" : "Confirm & search"}
        </button>
        <p className="mt-2 text-center text-xs text-ink/45">
          {ready
            ? "Looks good — launch the buyer fleet."
            : "Keep chatting until the item is clear."}
        </p>
      </aside>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs text-ink/45">{label}</dt>
      <dd className="truncate text-right font-medium">{value}</dd>
    </div>
  );
}
