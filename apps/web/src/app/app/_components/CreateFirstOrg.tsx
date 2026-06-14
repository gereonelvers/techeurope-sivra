"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

// First-run create-org card. POSTs to /api/orgs (which seeds the OWNER
// membership + default policy and sets the active-org cookie), then refreshes.
export function CreateFirstOrg() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    const res = await fetch("/api/orgs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    if (res.ok) {
      router.refresh();
    } else {
      const data = await res.json().catch(() => ({}));
      setError(data.error ?? "Could not create organization");
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-3xl font-semibold">Create your organization</h1>
      <p className="mt-2 text-sm leading-relaxed text-ink/65">
        You're not part of any organization yet. Create one to get started —
        you'll be the owner, and we'll seed a default escalation policy.
      </p>
      <form onSubmit={submit} className="mt-7 space-y-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          type="text"
          required
          placeholder="Acme GmbH"
          className="field"
        />
        {error ? <p className="text-sm text-red-700">{error}</p> : null}
        <button type="submit" disabled={busy} className="btn-accent w-full">
          {busy ? "Creating…" : "Create organization"}
        </button>
      </form>
    </div>
  );
}
