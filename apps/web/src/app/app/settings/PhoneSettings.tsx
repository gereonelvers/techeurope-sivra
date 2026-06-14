"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// Personal setting: view + change the phone number linked to YOUR account
// (not the org). Changing it texts a new confirm link; tapping it relinks.
export function PhoneSettings({
  currentPhoneDisplay,
}: {
  currentPhoneDisplay: string | null;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(!currentPhoneDisplay);
  const [phone, setPhone] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sent) return;
    const t = setInterval(() => router.refresh(), 4000);
    return () => clearInterval(t);
  }, [sent, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!phone.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/phone/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        if (data.alreadyVerified) {
          router.refresh();
          setEditing(false);
          return;
        }
        setSent(true);
      } else {
        setError(data.error ?? "Couldn't send the confirmation link.");
      }
    } catch {
      setError("Network error — please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-ink/10 bg-white/50 p-6">
      <h2 className="text-lg font-semibold">Your phone number</h2>
      <p className="mt-1 text-sm text-ink/60">
        Linked to your account for call-in ordering and approvals.
      </p>

      {currentPhoneDisplay && !editing && !sent ? (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <span className="font-medium tabular-nums">{currentPhoneDisplay}</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
            <span className="size-1.5 rounded-full bg-emerald-500" /> verified
          </span>
          <button
            type="button"
            onClick={() => {
              setEditing(true);
              setPhone("");
            }}
            className="text-sm font-medium text-accent hover:opacity-80"
          >
            Change
          </button>
        </div>
      ) : sent ? (
        <div className="mt-5">
          <p className="text-sm text-ink/75">
            We texted a confirmation link to <b>{phone}</b>. Tap it to finish — this
            updates automatically.
          </p>
          <button
            type="button"
            onClick={() => setSent(false)}
            className="mt-3 text-sm font-medium text-accent hover:opacity-80"
          >
            Use a different number
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-5 flex flex-col gap-3 sm:flex-row">
          <input
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            required
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+49 152 0446662"
            className="field sm:flex-1"
          />
          <button type="submit" disabled={busy} className="btn-accent whitespace-nowrap">
            {busy ? "Sending…" : "Send confirm link"}
          </button>
          {currentPhoneDisplay ? (
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setError(null);
              }}
              className="rounded-lg border border-ink/15 bg-white/60 px-4 py-3 text-sm font-semibold text-ink/70 transition hover:border-ink/30"
            >
              Cancel
            </button>
          ) : null}
        </form>
      )}
      {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
    </section>
  );
}
