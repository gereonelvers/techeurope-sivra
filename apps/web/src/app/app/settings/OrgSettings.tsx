"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  FLEET_TIERS,
  FLEET_TIER_ORDER,
  type FleetTier,
} from "@/lib/fleet-tiers";

export function OrgSettings({
  orgId,
  orgName,
  orgSlug,
  defaultFleetTier,
  canManage,
  startCreating,
}: {
  orgId: string;
  orgName: string;
  orgSlug: string;
  defaultFleetTier: FleetTier;
  canManage: boolean;
  startCreating: boolean;
}) {
  const router = useRouter();

  // Rename state
  const [name, setName] = useState(orgName);
  const [renaming, setRenaming] = useState(false);
  const [renameMsg, setRenameMsg] = useState<string | null>(null);
  const [renameErr, setRenameErr] = useState<string | null>(null);

  // Default fleet tier
  const [tier, setTier] = useState<FleetTier>(defaultFleetTier);
  const [savingTier, setSavingTier] = useState<FleetTier | null>(null);
  const [tierMsg, setTierMsg] = useState<string | null>(null);
  const [tierErr, setTierErr] = useState<string | null>(null);

  async function saveTier(next: FleetTier) {
    if (next === tier || savingTier) return;
    const prev = tier;
    setTier(next); // optimistic
    setSavingTier(next);
    setTierMsg(null);
    setTierErr(null);
    try {
      const res = await fetch(`/api/orgs/${orgId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ defaultFleetTier: next }),
      });
      if (res.ok) {
        setTierMsg("Saved.");
      } else {
        const data = await res.json().catch(() => ({}));
        setTier(prev); // rollback
        setTierErr(data.error ?? "Could not save.");
      }
    } catch {
      setTier(prev);
      setTierErr("Network error.");
    } finally {
      setSavingTier(null);
    }
  }

  // Create state
  const [showCreate, setShowCreate] = useState(startCreating);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);

  async function rename(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || name.trim() === orgName) return;
    setRenaming(true);
    setRenameMsg(null);
    setRenameErr(null);
    const res = await fetch(`/api/orgs/${orgId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setRenameMsg("Saved.");
      router.refresh();
    } else {
      setRenameErr(data.error ?? "Rename failed");
    }
    setRenaming(false);
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    setCreateErr(null);
    const res = await fetch("/api/orgs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim() }),
    });
    if (res.ok) {
      // The API sets the new org active; refresh to switch into it.
      router.push("/app");
      router.refresh();
    } else {
      const data = await res.json().catch(() => ({}));
      setCreateErr(data.error ?? "Create failed");
      setCreating(false);
    }
  }

  return (
    <div className="mt-8 space-y-8">
      {/* Org identity / rename */}
      <section className="rounded-xl border border-ink/10 bg-white/50 p-6">
        <h2 className="text-lg font-semibold">Organization</h2>
        <p className="mt-1 text-sm text-ink/60">
          Slug <code className="text-ink/70">/{orgSlug}</code> (fixed).
        </p>
        <form onSubmit={rename} className="mt-5 flex flex-col gap-3 sm:flex-row">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={!canManage}
            className="field sm:flex-1"
          />
          {canManage ? (
            <button
              type="submit"
              disabled={renaming}
              className="btn-accent whitespace-nowrap"
            >
              {renaming ? "Saving…" : "Save name"}
            </button>
          ) : null}
        </form>
        {!canManage ? (
          <p className="mt-2 text-sm text-ink/45">
            Only owners and admins can rename the organization.
          </p>
        ) : null}
        {renameMsg ? (
          <p className="mt-2 text-sm text-accent">{renameMsg}</p>
        ) : null}
        {renameErr ? (
          <p className="mt-2 text-sm text-red-700">{renameErr}</p>
        ) : null}
      </section>

      {/* Default browsing-fleet size */}
      <section className="rounded-xl border border-ink/10 bg-white/50 p-6">
        <h2 className="text-lg font-semibold">Browsing fleet</h2>
        <p className="mt-1 text-sm text-ink/60">
          How many buyer agents each search dispatches by default. You can still
          override this per search when you launch one.
        </p>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          {FLEET_TIER_ORDER.map((t) => {
            const meta = FLEET_TIERS[t];
            const selected = tier === t;
            return (
              <button
                key={t}
                type="button"
                onClick={() => saveTier(t)}
                disabled={!canManage || savingTier !== null}
                aria-pressed={selected}
                className={[
                  "rounded-xl border p-4 text-left transition",
                  selected
                    ? "border-accent bg-accent/[0.06] ring-1 ring-accent/40"
                    : "border-ink/10 bg-white/60 hover:border-ink/25",
                  !canManage ? "cursor-not-allowed opacity-70" : "",
                ].join(" ")}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold">{meta.label}</span>
                  <span className="text-xs tabular-nums text-ink/45">
                    {meta.n} agents
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink/55">{meta.blurb}</p>
                {selected ? (
                  <p className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-accent">
                    {savingTier === t ? "Saving…" : "Default"}
                  </p>
                ) : null}
              </button>
            );
          })}
        </div>
        {!canManage ? (
          <p className="mt-3 text-sm text-ink/45">
            Only owners and admins can change the default fleet size.
          </p>
        ) : null}
        {tierMsg ? <p className="mt-3 text-sm text-accent">{tierMsg}</p> : null}
        {tierErr ? <p className="mt-3 text-sm text-red-700">{tierErr}</p> : null}
      </section>

      {/* Create a new org */}
      <section className="rounded-xl border border-ink/10 bg-white/50 p-6">
        <h2 className="text-lg font-semibold">Create a new organization</h2>
        <p className="mt-1 text-sm text-ink/60">
          You'll be the owner; we seed a default escalation policy and switch you
          into it.
        </p>
        {showCreate ? (
          <form onSubmit={create} className="mt-5 flex flex-col gap-3 sm:flex-row">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              autoFocus
              placeholder="Acme GmbH"
              className="field sm:flex-1"
            />
            <button
              type="submit"
              disabled={creating}
              className="btn-accent whitespace-nowrap"
            >
              {creating ? "Creating…" : "Create"}
            </button>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="mt-4 text-sm font-medium text-accent hover:opacity-80"
          >
            + New organization
          </button>
        )}
        {createErr ? (
          <p className="mt-2 text-sm text-red-700">{createErr}</p>
        ) : null}
      </section>
    </div>
  );
}
