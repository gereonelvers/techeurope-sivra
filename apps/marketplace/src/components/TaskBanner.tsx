import { Skin } from "@/lib/skins";
import { formatPrice } from "@/lib/format";

// A slim banner showing the active episode's task spec. Read-only context for
// the agent / human driver. Does NOT reveal the target item id in the label
// text (keeps the task honest) but exposes it via a data attribute for tooling.
export function TaskBanner({
  skin,
  task,
}: {
  skin: Skin;
  task: { taskSpec: unknown; targetItemId: number | null };
}) {
  const t = skin.theme;
  const spec = (task.taskSpec ?? {}) as Record<string, unknown>;

  const parts: string[] = [];
  if (spec.category) parts.push(String(spec.category));
  if (spec.brand) parts.push(`brand: ${spec.brand}`);
  if (spec.minCondition) parts.push(`≥ ${spec.minCondition}`);
  if (typeof spec.maxPriceCents === "number") {
    parts.push(`≤ ${formatPrice(spec.maxPriceCents)}`);
  }
  if (spec.city) parts.push(String(spec.city));

  return (
    <div
      className={`${t.accentSoft} ${t.accentSoftText} border-b ${t.surfaceBorder}`}
      data-qm="task-banner"
      data-target-item-id={task.targetItemId ?? ""}
    >
      <div className="mx-auto max-w-6xl px-4 py-2 text-sm">
        <span className="font-semibold">Active task:</span> buy the cheapest{" "}
        <span data-qm="task-spec">{parts.join(" · ") || "matching item"}</span>
      </div>
    </div>
  );
}
