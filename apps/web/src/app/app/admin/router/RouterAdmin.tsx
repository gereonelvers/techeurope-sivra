"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

interface Scores {
  person_acc?: number;
  urgency_acc?: number;
  delegate_acc?: number;
  exact_match?: number;
  [k: string]: number | undefined;
}
interface RunRow {
  id: string;
  startedAt: string;
  finishedAt: string | null;
  status: string;
  triggeredBy: string;
  sampleCount: number;
  championModelId: string | null;
  challengerModelId: string | null;
  championScores: Scores | null;
  challengerScores: Scores | null;
  decision: string | null;
  notes: string | null;
}
interface ConfigView {
  activeModelId: string;
  baseModel: string;
  version: number;
  autoRetrainEnabled: boolean;
  minSamples: number;
  lastTrainedAt: string | null;
  lastTrainedSampleCount: number;
}

function shortId(id: string | null): string {
  if (!id) return "—";
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}
function pct(n: number | undefined): string {
  return n === undefined || n === null ? "—" : `${(n * 100).toFixed(0)}%`;
}
function ts(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

const DECISION_STYLE: Record<string, string> = {
  promoted: "bg-emerald-100 text-emerald-800",
  kept: "bg-ink/10 text-ink/70",
  skipped: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
};
const STATUS_STYLE: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800",
  running: "bg-blue-100 text-blue-700",
  failed: "bg-red-100 text-red-700",
};

export function RouterAdmin({
  initialConfig,
  sampleCount,
  runs,
}: {
  initialConfig: ConfigView;
  sampleCount: number;
  runs: RunRow[];
}) {
  const router = useRouter();
  const [config, setConfig] = useState(initialConfig);
  const [minSamplesInput, setMinSamplesInput] = useState(String(initialConfig.minSamples));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const pctToThreshold = Math.min(
    100,
    config.minSamples > 0 ? Math.round((sampleCount / config.minSamples) * 100) : 100,
  );
  const ready = sampleCount >= config.minSamples;

  async function patchConfig(patch: { autoRetrainEnabled?: boolean; minSamples?: number }) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch("/api/router/config", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(d.error ?? "Update failed");
      } else if (d.config) {
        setConfig((c) => ({
          ...c,
          autoRetrainEnabled: d.config.autoRetrainEnabled,
          minSamples: d.config.minSamples,
        }));
        setMinSamplesInput(String(d.config.minSamples));
        setNotice("Saved.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function retrainNow() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch("/api/router/retrain", { method: "POST" });
      const d = await res.json().catch(() => ({}));
      if (!res.ok && !("triggered" in d)) {
        setError(d.error ?? `Trigger failed (${res.status})`);
      } else {
        setNotice(d.message ?? (d.triggered ? "Retrain triggered." : "Retrain not triggered."));
        router.refresh();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-8 space-y-10">
      {error && (
        <p className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{error}</p>
      )}
      {notice && (
        <p className="rounded-lg bg-accent/10 px-4 py-2 text-sm text-accent">{notice}</p>
      )}

      {/* Active model */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink/50">
          Active model
        </h2>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-ink/10 bg-white/50 p-4">
            <p className="text-xs text-ink/50">Live model (job id)</p>
            <p className="mt-1 break-all font-mono text-sm">{config.activeModelId}</p>
          </div>
          <div className="rounded-xl border border-ink/10 bg-white/50 p-4">
            <p className="text-xs text-ink/50">Version</p>
            <p className="mt-1 text-2xl font-semibold">v{config.version}</p>
          </div>
          <div className="rounded-xl border border-ink/10 bg-white/50 p-4">
            <p className="text-xs text-ink/50">Base model</p>
            <p className="mt-1 font-mono text-xs">{config.baseModel}</p>
          </div>
        </div>
        <p className="mt-2 text-xs text-ink/50">
          Last trained {ts(config.lastTrainedAt)} · watermark{" "}
          {config.lastTrainedSampleCount} samples
        </p>
      </section>

      {/* Feedback vs threshold */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink/50">
          Feedback since last train
        </h2>
        <div className="mt-3 rounded-xl border border-ink/10 bg-white/50 p-5">
          <div className="flex items-baseline justify-between">
            <p className="text-3xl font-semibold">
              {sampleCount}
              <span className="ml-2 text-base font-normal text-ink/50">
                / {config.minSamples} needed
              </span>
            </p>
            <span
              className={[
                "rounded-full px-3 py-1 text-xs font-medium",
                ready ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800",
              ].join(" ")}
            >
              {ready ? "threshold met" : "gathering feedback"}
            </span>
          </div>
          <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-ink/10">
            <div
              className={ready ? "h-full bg-emerald-500" : "h-full bg-accent"}
              style={{ width: `${pctToThreshold}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-ink/50">
            Resolved escalations since the last successful train. The daily cron
            retrains once this reaches the threshold.
          </p>
        </div>
      </section>

      {/* Controls */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink/50">
          Auto-retrain
        </h2>
        <div className="mt-3 space-y-4 rounded-xl border border-ink/10 bg-white/50 p-5">
          <label className="flex items-center justify-between">
            <span className="text-sm">
              <span className="font-medium">Enable daily auto-retrain</span>
              <span className="mt-0.5 block text-xs text-ink/50">
                When off, the cron records a skipped run and does nothing.
              </span>
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => patchConfig({ autoRetrainEnabled: !config.autoRetrainEnabled })}
              className={[
                "relative inline-flex h-6 w-11 items-center rounded-full transition",
                config.autoRetrainEnabled ? "bg-accent" : "bg-ink/20",
                busy ? "opacity-50" : "",
              ].join(" ")}
            >
              <span
                className={[
                  "inline-block h-4 w-4 transform rounded-full bg-white transition",
                  config.autoRetrainEnabled ? "translate-x-6" : "translate-x-1",
                ].join(" ")}
              />
            </button>
          </label>

          <div className="flex items-end gap-3 border-t border-ink/10 pt-4">
            <label className="flex-1">
              <span className="text-sm font-medium">Sample threshold (minSamples)</span>
              <span className="mt-0.5 block text-xs text-ink/50">
                Resolved-feedback rows required before a retrain runs.
              </span>
              <input
                type="number"
                min={0}
                value={minSamplesInput}
                onChange={(e) => setMinSamplesInput(e.target.value)}
                className="mt-2 w-32 rounded-lg border border-ink/15 bg-white px-3 py-2 text-sm"
              />
            </label>
            <button
              type="button"
              disabled={busy || minSamplesInput === String(config.minSamples)}
              onClick={() => patchConfig({ minSamples: Number(minSamplesInput) })}
              className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-paper transition hover:opacity-90 disabled:opacity-40"
            >
              Save threshold
            </button>
          </div>

          <div className="border-t border-ink/10 pt-4">
            <button
              type="button"
              disabled={busy}
              onClick={retrainNow}
              className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
            >
              {busy ? "Working…" : "Retrain now"}
            </button>
            <p className="mt-2 text-xs text-ink/50">
              Triggers a retrain → eval → promote cycle immediately (manual run).
            </p>
          </div>
        </div>
      </section>

      {/* Run history */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink/50">
          Training run history
        </h2>
        {runs.length === 0 ? (
          <p className="mt-3 rounded-xl border border-dashed border-ink/15 p-6 text-sm text-ink/50">
            No retrain runs yet. The first daily cron (or a manual “Retrain now”)
            will appear here with champion-vs-challenger eval scores and the
            promote/keep decision.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto rounded-xl border border-ink/10">
            <table className="w-full text-sm">
              <thead className="bg-ink/5 text-left text-xs uppercase tracking-wide text-ink/50">
                <tr>
                  <th className="px-3 py-2 font-medium">Started</th>
                  <th className="px-3 py-2 font-medium">Trigger</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Samples</th>
                  <th className="px-3 py-2 font-medium">Champion → Challenger</th>
                  <th className="px-3 py-2 font-medium">Exact (champ / chall)</th>
                  <th className="px-3 py-2 font-medium">Decision</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="border-t border-ink/10 align-top">
                    <td className="px-3 py-2 whitespace-nowrap text-xs">
                      {ts(r.startedAt)}
                    </td>
                    <td className="px-3 py-2 text-xs">{r.triggeredBy}</td>
                    <td className="px-3 py-2">
                      <span
                        className={[
                          "rounded-full px-2 py-0.5 text-xs font-medium",
                          STATUS_STYLE[r.status] ?? "bg-ink/10 text-ink/70",
                        ].join(" ")}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs">{r.sampleCount}</td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {shortId(r.championModelId)} → {shortId(r.challengerModelId)}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {pct(r.championScores?.exact_match)} /{" "}
                      {pct(r.challengerScores?.exact_match)}
                    </td>
                    <td className="px-3 py-2">
                      {r.decision ? (
                        <span
                          className={[
                            "rounded-full px-2 py-0.5 text-xs font-medium",
                            DECISION_STYLE[r.decision] ?? "bg-ink/10 text-ink/70",
                          ].join(" ")}
                          title={r.notes ?? undefined}
                        >
                          {r.decision}
                        </span>
                      ) : (
                        <span className="text-xs text-ink/40">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
