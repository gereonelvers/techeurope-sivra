// Idempotent seed for the singleton RouterConfig. Run after `prisma db push`:
//   node prisma/seed-router-config.mjs
// Reads DATABASE_URL from the environment (apps/web/.env is loaded by Prisma's
// own dotenv when run via npm scripts; here we load it explicitly so the bare
// `node` invocation works too). Safe to run repeatedly: it only creates a row
// when none exists and never overwrites a promoted activeModelId.
import { PrismaClient } from "@prisma/client";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// Minimal .env loader (avoids a dotenv dependency in the seed path).
const __dirname = dirname(fileURLToPath(import.meta.url));
if (!process.env.DATABASE_URL) {
  for (const p of [join(__dirname, "..", ".env"), join(__dirname, "..", "..", "..", ".env")]) {
    try {
      for (const line of readFileSync(p, "utf8").split("\n")) {
        const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
        if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
      }
    } catch {
      /* file may not exist; ignore */
    }
  }
}

// The current champion fine-tune (delegation-router-sft), addressed by job id.
const CHAMPION = "1c0bc366-42f1-414f-86ed-1ee503f2bbc4";

const prisma = new PrismaClient();

async function main() {
  const existing = await prisma.routerConfig.findFirst();
  if (existing) {
    console.log(
      `RouterConfig already present (id=${existing.id}, activeModelId=${existing.activeModelId}, version=${existing.version}) — leaving as-is.`,
    );
    return;
  }
  const created = await prisma.routerConfig.create({
    data: { activeModelId: CHAMPION },
  });
  console.log(
    `Seeded RouterConfig id=${created.id} activeModelId=${created.activeModelId} version=${created.version}`,
  );
}

main()
  .catch((e) => {
    console.error("seed-router-config failed:", e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
