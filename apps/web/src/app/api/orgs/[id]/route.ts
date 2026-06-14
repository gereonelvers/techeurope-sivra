import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { assertCanManage, UnauthorizedError, ForbiddenError } from "@/lib/org";
import { isFleetTier } from "@/lib/fleet-tiers";

// PATCH /api/orgs/:id — update org settings (name and/or default browsing-fleet
// tier). OWNER/ADMIN only. Either field may be sent independently.
export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    await assertCanManage(params.id); // membership + RBAC

    const body = (await req.json().catch(() => ({}))) as {
      name?: string;
      defaultFleetTier?: string;
    };

    const data: { name?: string; defaultFleetTier?: string } = {};

    if (body.name !== undefined) {
      const name = String(body.name).trim();
      if (!name) {
        return NextResponse.json({ error: "name is required" }, { status: 400 });
      }
      data.name = name;
    }

    if (body.defaultFleetTier !== undefined) {
      const tier = String(body.defaultFleetTier).toUpperCase();
      if (!isFleetTier(tier)) {
        return NextResponse.json(
          { error: "defaultFleetTier must be SMALL, MEDIUM, or DEEP" },
          { status: 400 },
        );
      }
      data.defaultFleetTier = tier;
    }

    if (Object.keys(data).length === 0) {
      return NextResponse.json({ error: "nothing to update" }, { status: 400 });
    }

    const org = await prisma.organization.update({
      where: { id: params.id },
      data,
      select: { id: true, name: true, slug: true, defaultFleetTier: true },
    });
    return NextResponse.json({ org });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
