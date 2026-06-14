import type { DefaultSession } from "next-auth";

// Surface the DB user id on the session (database-session strategy populates it,
// but the default types mark it optional/absent). Lets org.ts read session.user.id.
declare module "next-auth" {
  interface Session {
    user: {
      id: string;
    } & DefaultSession["user"];
  }
}
