// Auth.js v5 catch-all route. Mounts the GET/POST handlers exported from
// src/lib/auth.ts (sign-in, callback, sign-out, magic-link verification).
import { handlers } from "@/lib/auth";

export const { GET, POST } = handlers;
