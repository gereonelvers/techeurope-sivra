import { PrismaClient } from "@prisma/client";

// Single PrismaClient reused across hot-reloads in dev and across the
// serverless/module cache in prod, so we don't exhaust Postgres connections.
// apps/web is the ONLY writer of the product DB — import { prisma } from here.
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
