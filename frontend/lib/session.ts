import "server-only";

import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

// Verifies the session cookies the API sets on login (backend/app/auth.py), so pages can be gated
// on the server without a round trip. Both sides must share WW_SECRET.
//
// One cookie per role (ww_collector, ww_dealer, ww_satin, ww_household, ww_ops), so everyone in a
// demo can be signed in in the same browser — which is how the demo stage works.

export type Role = "collector" | "dealer" | "satin" | "household" | "ops";

const DEV_SECRET = "worthywaste-dev-secret-change-me";

function secret(): string {
  const s = process.env.WW_SECRET;
  if (s) return s;
  if (process.env.VERCEL_ENV === "production") throw new Error("WW_SECRET must be set in production");
  return DEV_SECRET;
}

const b64url = (buf: Buffer) => buf.toString("base64url");

/** User id from a valid, unexpired token for this role; otherwise null. */
export function readToken(token: string | undefined, role: Role): number | null {
  if (!token || !token.includes(".")) return null;
  const dot = token.lastIndexOf(".");
  const payload = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  const want = b64url(createHmac("sha256", secret()).update(payload).digest());
  const a = Buffer.from(sig);
  const b = Buffer.from(want);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  try {
    const data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as { r: string; id: number; exp: number };
    if (data.r !== role || data.exp * 1000 < Date.now()) return null;
    return Number(data.id);
  } catch {
    return null;
  }
}

export async function sessionId(role: Role): Promise<number | null> {
  const store = await cookies();
  return readToken(store.get(`ww_${role}`)?.value, role);
}

/** Use at the top of a page: returns the user id, or sends the visitor to the login page. */
export async function requireSession(role: Role): Promise<number> {
  const id = await sessionId(role);
  if (id === null) redirect(`/login?role=${role}`);
  return id;
}
