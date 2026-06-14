"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const ORG_ROLES = ["OWNER", "ADMIN", "MEMBER"] as const;
const PURCHASING_ROLES = ["buyer", "procurement_lead", "manager"] as const;

interface MemberRow {
  id: string;
  email: string;
  name: string | null;
  role: string;
  purchasingRole: string | null;
  approvalLimitCents: number | null;
  isSelf: boolean;
}
interface InviteRow {
  id: string;
  email: string;
  role: string;
  purchasingRole: string | null;
  expiresAt: string;
}

function euros(cents: number | null): string {
  if (cents === null || cents === undefined) return "";
  return (cents / 100).toFixed(2);
}

export function TeamManager({
  members,
  invites,
  canManage,
}: {
  members: MemberRow[];
  invites: InviteRow[];
  canManage: boolean;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function patchMember(
    id: string,
    body: Record<string, unknown>,
  ) {
    setBusyId(id);
    setError(null);
    const res = await fetch(`/api/members/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setError(d.error ?? "Update failed");
    } else {
      router.refresh();
    }
    setBusyId(null);
  }

  async function removeMember(id: string) {
    if (!confirm("Remove this member from the organization?")) return;
    setBusyId(id);
    setError(null);
    const res = await fetch(`/api/members/${id}`, { method: "DELETE" });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setError(d.error ?? "Remove failed");
    } else {
      router.refresh();
    }
    setBusyId(null);
  }

  async function revokeInvite(id: string) {
    setBusyId(id);
    setError(null);
    const res = await fetch(`/api/invites/${id}`, { method: "DELETE" });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setError(d.error ?? "Revoke failed");
    } else {
      router.refresh();
    }
    setBusyId(null);
  }

  return (
    <div className="mt-8 space-y-10">
      {error ? (
        <p className="rounded-lg border border-red-300 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          {error}
        </p>
      ) : null}

      {/* Members */}
      <section>
        <h2 className="text-lg font-semibold">Members</h2>
        <div className="mt-3 overflow-x-auto rounded-xl border border-ink/10">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="bg-ink/[0.03] text-left text-xs uppercase tracking-[0.1em] text-ink/45">
              <tr>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Purchasing</th>
                <th className="px-4 py-3 font-medium">Limit (€)</th>
                {canManage ? <th className="px-4 py-3" /> : null}
              </tr>
            </thead>
            <tbody className="divide-y divide-ink/8">
              {members.map((m) => (
                <tr key={m.id} className="bg-white/40">
                  <td className="px-4 py-3">
                    <span className="font-medium">{m.email}</span>
                    {m.isSelf ? (
                      <span className="ml-2 text-xs text-ink/40">(you)</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    {canManage ? (
                      <select
                        defaultValue={m.role}
                        disabled={busyId === m.id}
                        onChange={(e) =>
                          patchMember(m.id, { role: e.target.value })
                        }
                        className="rounded-md border border-ink/15 bg-white px-2 py-1 text-sm"
                      >
                        {ORG_ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    ) : (
                      m.role
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {canManage ? (
                      <select
                        defaultValue={m.purchasingRole ?? ""}
                        disabled={busyId === m.id}
                        onChange={(e) =>
                          patchMember(m.id, {
                            purchasingRole: e.target.value || null,
                          })
                        }
                        className="rounded-md border border-ink/15 bg-white px-2 py-1 text-sm"
                      >
                        <option value="">—</option>
                        {PURCHASING_ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r.replace(/_/g, " ")}
                          </option>
                        ))}
                      </select>
                    ) : (
                      m.purchasingRole?.replace(/_/g, " ") ?? "—"
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {canManage ? (
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        defaultValue={euros(m.approvalLimitCents)}
                        disabled={busyId === m.id}
                        placeholder="∞"
                        onBlur={(e) => {
                          const v = e.target.value.trim();
                          const cents =
                            v === "" ? null : Math.round(Number(v) * 100);
                          if (cents !== m.approvalLimitCents) {
                            patchMember(m.id, { approvalLimitCents: cents });
                          }
                        }}
                        className="w-24 rounded-md border border-ink/15 bg-white px-2 py-1 text-sm"
                      />
                    ) : m.approvalLimitCents === null ? (
                      "∞"
                    ) : (
                      `€${euros(m.approvalLimitCents)}`
                    )}
                  </td>
                  {canManage ? (
                    <td className="px-4 py-3 text-right">
                      {!m.isSelf ? (
                        <button
                          onClick={() => removeMember(m.id)}
                          disabled={busyId === m.id}
                          className="text-sm font-medium text-red-700 hover:opacity-80"
                        >
                          Remove
                        </button>
                      ) : null}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Pending invites */}
      {invites.length > 0 ? (
        <section>
          <h2 className="text-lg font-semibold">Pending invites</h2>
          <ul className="mt-3 space-y-2">
            {invites.map((i) => (
              <li
                key={i.id}
                className="flex items-center justify-between rounded-lg border border-ink/10 bg-white/40 px-4 py-3 text-sm"
              >
                <div>
                  <span className="font-medium">{i.email}</span>
                  <span className="ml-2 text-ink/55">
                    {i.role.toLowerCase()}
                    {i.purchasingRole
                      ? ` · ${i.purchasingRole.replace(/_/g, " ")}`
                      : ""}
                  </span>
                </div>
                {canManage ? (
                  <button
                    onClick={() => revokeInvite(i.id)}
                    disabled={busyId === i.id}
                    className="text-sm font-medium text-red-700 hover:opacity-80"
                  >
                    Revoke
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Invite form */}
      {canManage ? <InviteForm /> : null}
    </div>
  );
}

function InviteForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("MEMBER");
  const [purchasingRole, setPurchasingRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setMsg(null);
    setErr(null);
    const res = await fetch("/api/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email.trim(),
        role,
        purchasingRole: purchasingRole || null,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setMsg(
        data.emailSent
          ? `Invite sent to ${email.trim()}.`
          : `Invite created for ${email.trim()} (email delivery is off).`,
      );
      setEmail("");
      setPurchasingRole("");
      router.refresh();
    } else {
      setErr(data.error ?? "Invite failed");
    }
    setBusy(false);
  }

  return (
    <section className="rounded-xl border border-ink/10 bg-white/50 p-6">
      <h2 className="text-lg font-semibold">Invite a member</h2>
      <p className="mt-1 text-sm text-ink/60">
        Sends an email with an accept link. They join when they accept.
      </p>
      <form onSubmit={submit} className="mt-5 space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            required
            placeholder="person@company.com"
            className="field sm:col-span-3"
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="field"
          >
            {ORG_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <select
            value={purchasingRole}
            onChange={(e) => setPurchasingRole(e.target.value)}
            className="field"
          >
            <option value="">No purchasing role</option>
            {PURCHASING_ROLES.map((r) => (
              <option key={r} value={r}>
                {r.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={busy}
            className="btn-accent whitespace-nowrap"
          >
            {busy ? "Sending…" : "Send invite"}
          </button>
        </div>
        {msg ? <p className="text-sm text-accent">{msg}</p> : null}
        {err ? <p className="text-sm text-red-700">{err}</p> : null}
      </form>
    </section>
  );
}
