import { PrismaClient } from "@prisma/client";

// Reuse a single PrismaClient across hot-reloads in dev and across the
// serverless module cache in prod to avoid exhausting SQLite connections.
const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined;
};

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({
    log: process.env.NODE_ENV === "development" ? ["error", "warn"] : ["error"],
  });

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}
