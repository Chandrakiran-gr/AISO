/**
 * GET /api/token
 *
 * Returns a short-lived API token for the current NextAuth session.
 * The token is signed with AUTH_SECRET — the same secret FastAPI uses
 * to verify incoming requests. This bridges NextAuth ↔ FastAPI auth.
 *
 * Token TTL: 5 minutes (frontend should re-fetch before each API call
 * or cache with expiry).
 */
import { auth } from "@/auth";
import { SignJWT } from "jose";
import { NextResponse } from "next/server";

const SECRET = new TextEncoder().encode(process.env.AUTH_SECRET ?? "dev-secret-change-me");

export async function GET() {
  const session = await auth();

  if (!session?.user) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }

  // Create a compact JWT: sub = user id/email, exp = 5 minutes
  const token = await new SignJWT({
    sub:   session.user.id ?? session.user.email ?? "unknown",
    email: session.user.email ?? "",
    name:  session.user.name  ?? "",
  })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("5m")
    .setIssuer("aiso-web")
    .setAudience("aiso-api")
    .sign(SECRET);

  return NextResponse.json({ token });
}
