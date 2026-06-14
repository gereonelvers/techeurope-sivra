"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// Required onboarding step (for website sign-ups): add + confirm a phone. We
// text a confirm link; tapping it (proof of possession) links the number. While
// we wait, this polls so the page advances the moment they tap the link.
export function AddPhone() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Once the link is sent, poll for confirmation (the link is tapped on their
  // phone; a refresh re-checks the server-side gate in the layout).
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

  if (sent) {
    return (
      <div>
        <h1 className="text-3xl font-semibold">Check your phone</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink/65">
          We texted a confirmation link to <b>{phone}</b>. Tap it to finish — this
          page updates automatically once you do.
        </p>
        <button
          type="button"
          onClick={() => {
            setSent(false);
            setError(null);
          }}
          className="mt-6 text-sm font-medium text-accent hover:opacity-80"
        >
          Use a different number
        </button>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-3xl font-semibold">Add your phone number</h1>
      <p className="mt-2 text-sm leading-relaxed text-ink/65">
        sivra links your phone to your account so you can place orders by calling
        in, and so approvals reach you fast. We'll text you a link to confirm it.
      </p>
      <form onSubmit={submit} className="mt-7 space-y-4">
        <div>
          <label htmlFor="phone" className="mb-1.5 block text-sm font-medium text-ink/80">
            Phone number
          </label>
          <input
            id="phone"
            name="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            required
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+49 152 0446662"
            className="field"
          />
          <p className="mt-1.5 text-xs text-ink/45">
            Any format is fine — spaces, dashes, with or without “+”.
          </p>
        </div>
        {error ? <p className="text-sm text-red-700">{error}</p> : null}
        <button type="submit" disabled={busy} className="btn-accent w-full">
          {busy ? "Sending…" : "Send confirmation link"}
        </button>
      </form>
    </div>
  );
}
