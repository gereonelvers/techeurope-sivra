// Order status badge with a calm, status-keyed palette. Server-safe (no hooks).
const STYLES: Record<string, string> = {
  DRAFT: "bg-ink/8 text-ink/60",
  SEARCHING: "bg-amber-500/15 text-amber-800",
  ESCALATED: "bg-accent/15 text-accent",
  APPROVED: "bg-emerald-600/15 text-emerald-800",
  DECLINED: "bg-red-600/15 text-red-800",
  PURCHASING: "bg-amber-500/15 text-amber-800",
  COMPLETED: "bg-emerald-600/15 text-emerald-800",
  FAILED: "bg-red-600/15 text-red-800",
  CANCELLED: "bg-ink/8 text-ink/50",
};

const LABELS: Record<string, string> = {
  DRAFT: "Draft",
  SEARCHING: "Searching",
  ESCALATED: "Needs sign-off",
  APPROVED: "Approved",
  DECLINED: "Declined",
  PURCHASING: "Purchasing",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

export function StatusBadge({ status }: { status: string }) {
  const style = STYLES[status] ?? "bg-ink/8 text-ink/60";
  const label = LABELS[status] ?? status;
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-3 py-1 text-xs font-semibold ${style}`}
    >
      {label}
    </span>
  );
}
