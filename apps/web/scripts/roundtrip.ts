// Round-trip smoke test: create an Organization + User + Membership, read them
// back, then delete them — leaving the DB clean. Run with:
//   npx tsx scripts/roundtrip.ts
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const stamp = Date.now();
  const slug = `roundtrip-${stamp}`;
  const email = `roundtrip+${stamp}@example.com`;

  console.log("→ creating Organization, User, Membership…");
  const org = await prisma.organization.create({
    data: { name: "Round-trip Org", slug },
  });
  const user = await prisma.user.create({
    data: { email, name: "Round-trip User" },
  });
  const membership = await prisma.membership.create({
    data: {
      orgId: org.id,
      userId: user.id,
      role: "OWNER",
      purchasingRole: "manager",
    },
  });

  console.log("→ reading back…");
  const readBack = await prisma.membership.findUnique({
    where: { id: membership.id },
    include: { org: true, user: true },
  });
  if (!readBack || readBack.org.id !== org.id || readBack.user.id !== user.id) {
    throw new Error("round-trip read mismatch");
  }
  console.log(
    `   ✓ membership ${readBack.id} → org "${readBack.org.name}" (${readBack.org.slug}), user ${readBack.user.email}, role ${readBack.role}/${readBack.purchasingRole}`,
  );

  console.log("→ cleaning up…");
  // Membership cascades on org/user delete; delete explicitly to be safe.
  await prisma.membership.delete({ where: { id: membership.id } });
  await prisma.user.delete({ where: { id: user.id } });
  await prisma.organization.delete({ where: { id: org.id } });

  const remaining = await prisma.organization.findUnique({ where: { slug } });
  if (remaining) throw new Error("cleanup failed — org still present");

  console.log("✓ round-trip OK, DB clean");
}

main()
  .catch((e) => {
    console.error("✗ round-trip FAILED:", e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
