import { redirect } from "next/navigation";

// The standalone Fleet view was merged into the Orders hub (the single
// operational view). Live fleet activity now surfaces inline on /app/orders.
// We keep this route as a permanent redirect so old links / bookmarks resolve.
export const dynamic = "force-dynamic";

export default function FleetPage() {
  redirect("/app/orders");
}
