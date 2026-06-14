"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const PURCHASING_ROLES = ["buyer", "procurement_lead", "manager"] as const;
const URGENCY_TIERS = ["async", "urgent_push", "voice"] as const;

interface Rule {
  maxBudgetCents: number | null;
  targetPurchasingRole: string;
  urgency: string;
  autoApprove: boolean;
  minConfidence: number;
}

// cents <-> euro-string helpers for the budget inputs.
function toEuro(cents: number | null): string {
  return cents === null || cents === undefined ? "" : (cents / 100).toString();
}
function toCents(euro: string): number | null {
  const v = euro.trim();
  if (v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n * 100) : null;
}

export function PolicyEditor({
  initialRules,
  initialAutoApproveMaxCents,
  initialVoiceOverageRatio,
  canManage,
}: {
  initialRules: Rule[];
  initialAutoApproveMaxCents: number;
  initialVoiceOverageRatio: number;
  canManage: boolean;
}) {
  const router = useRouter();
  const [rules, setRules] = useState<Rule[]>(initialRules);
  const [autoApproveMaxEuro, setAutoApproveMaxEuro] = useState(
    toEuro(initialAutoApproveMaxCents),
  );
  const [voiceOverageRatio, setVoiceOverageRatio] = useState(
    String(initialVoiceOverageRatio),
  );
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  function updateRule(i: number, patch: Partial<Rule>) {
    setRules((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }
  function addRule() {
    setRules((rs) => [
      ...rs,
      {
        maxBudgetCents: null,
        targetPurchasingRole: "manager",
        urgency: "voice",
        autoApprove: false,
        minConfidence: 0.5,
      },
    ]);
  }
  function removeRule(i: number) {
    setRules((rs) => rs.filter((_, idx) => idx !== i));
  }
  function move(i: number, dir: -1 | 1) {
    setRules((rs) => {
      const j = i + dir;
      if (j < 0 || j >= rs.length) return rs;
      const copy = [...rs];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      return copy;
    });
  }

  async function save() {
    setBusy(true);
    setMsg(null);
    setErr(null);
    const res = await fetch("/api/policies", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rules,
        autoApproveMaxCents: toCents(autoApproveMaxEuro) ?? 0,
        voiceOverageRatio: Number(voiceOverageRatio) || 1,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setMsg("Policy saved.");
      router.refresh();
    } else {
      setErr(data.error ?? "Save failed");
    }
    setBusy(false);
  }

  const ro = !canManage;

  return (
    <div className="mt-8 space-y-8">
      {/* Ordered rules */}
      <section>
        <h2 className="text-lg font-semibold">Escalation rules</h2>
        <p className="mt-1 text-sm text-ink/60">
          Evaluated top-to-bottom. The first band whose budget covers the
          purchase decides the target role and urgency. Leave the budget blank
          for an open-ended catch-all.
        </p>

        <div className="mt-4 space-y-3">
          {rules.map((r, i) => (
            <div
              key={i}
              className="rounded-xl border border-ink/10 bg-white/50 p-4"
            >
              <div className="flex items-start gap-3">
                <span className="mt-2 text-xs font-semibold text-ink/40">
                  #{i + 1}
                </span>
                <div className="grid flex-1 gap-3 sm:grid-cols-2">
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-ink/55">
                      Up to budget (€, blank = ∞)
                    </span>
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      disabled={ro}
                      value={toEuro(r.maxBudgetCents)}
                      placeholder="∞"
                      onChange={(e) =>
                        updateRule(i, { maxBudgetCents: toCents(e.target.value) })
                      }
                      className="field"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-ink/55">
                      Target purchasing role
                    </span>
                    <select
                      disabled={ro}
                      value={r.targetPurchasingRole}
                      onChange={(e) =>
                        updateRule(i, { targetPurchasingRole: e.target.value })
                      }
                      className="field"
                    >
                      {PURCHASING_ROLES.map((pr) => (
                        <option key={pr} value={pr}>
                          {pr.replace(/_/g, " ")}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-ink/55">
                      Urgency
                    </span>
                    <select
                      disabled={ro}
                      value={r.urgency}
                      onChange={(e) =>
                        updateRule(i, { urgency: e.target.value })
                      }
                      className="field"
                    >
                      {URGENCY_TIERS.map((u) => (
                        <option key={u} value={u}>
                          {u.replace(/_/g, " ")}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-ink/55">
                      Min confidence (0–1)
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step="0.05"
                      disabled={ro}
                      value={r.minConfidence}
                      onChange={(e) =>
                        updateRule(i, {
                          minConfidence: Number(e.target.value),
                        })
                      }
                      className="field"
                    />
                  </label>
                  <label className="flex items-center gap-2 sm:col-span-2">
                    <input
                      type="checkbox"
                      disabled={ro}
                      checked={r.autoApprove}
                      onChange={(e) =>
                        updateRule(i, { autoApprove: e.target.checked })
                      }
                      className="h-4 w-4 accent-accent"
                    />
                    <span className="text-sm text-ink/70">
                      Auto-approve when confidence ≥ min (no human sign-off)
                    </span>
                  </label>
                </div>
                {!ro ? (
                  <div className="flex flex-col gap-1 text-ink/40">
                    <button
                      type="button"
                      onClick={() => move(i, -1)}
                      disabled={i === 0}
                      className="rounded px-1 hover:text-accent disabled:opacity-30"
                      aria-label="Move up"
                    >
                      ▲
                    </button>
                    <button
                      type="button"
                      onClick={() => move(i, 1)}
                      disabled={i === rules.length - 1}
                      className="rounded px-1 hover:text-accent disabled:opacity-30"
                      aria-label="Move down"
                    >
                      ▼
                    </button>
                    <button
                      type="button"
                      onClick={() => removeRule(i)}
                      className="rounded px-1 text-red-700 hover:opacity-80"
                      aria-label="Remove rule"
                    >
                      ✕
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>

        {!ro ? (
          <button
            type="button"
            onClick={addRule}
            className="mt-3 text-sm font-medium text-accent hover:opacity-80"
          >
            + Add rule
          </button>
        ) : null}
      </section>

      {/* Global knobs */}
      <section className="rounded-xl border border-ink/10 bg-white/50 p-5">
        <h2 className="text-lg font-semibold">Global limits</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-ink/55">
              Auto-approve max (€)
            </span>
            <input
              type="number"
              min={0}
              step="0.01"
              disabled={ro}
              value={autoApproveMaxEuro}
              onChange={(e) => setAutoApproveMaxEuro(e.target.value)}
              className="field"
            />
            <span className="mt-1 block text-xs text-ink/45">
              Hard ceiling on any auto-approval, regardless of rule.
            </span>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-ink/55">
              Voice overage ratio
            </span>
            <input
              type="number"
              min={1}
              step="0.1"
              disabled={ro}
              value={voiceOverageRatio}
              onChange={(e) => setVoiceOverageRatio(e.target.value)}
              className="field"
            />
            <span className="mt-1 block text-xs text-ink/45">
              Escalate by voice when proposed value exceeds budget × this.
            </span>
          </label>
        </div>
      </section>

      {!ro ? (
        <div className="flex items-center gap-4">
          <button onClick={save} disabled={busy} className="btn-accent">
            {busy ? "Saving…" : "Save policy"}
          </button>
          {msg ? <span className="text-sm text-accent">{msg}</span> : null}
          {err ? <span className="text-sm text-red-700">{err}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
