/**
 * Authenticated fetch helper for FastAPI calls.
 *
 * Automatically:
 *  1. Fetches a short-lived JWT from /api/token (cached for 4 min)
 *  2. Attaches Authorization: Bearer <token> to every request
 *  3. Re-fetches the token if it's about to expire (< 60s remaining)
 *
 * Usage:
 *   import { apiFetch } from "@/lib/apifetch";
 *   const data = await apiFetch("/api/v1/clients");
 */

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// In-memory token cache (tab-scoped)
let cachedToken: string | null = null;
let tokenExpiry  = 0; // Unix ms

async function getToken(): Promise<string | null> {
  const now = Date.now();
  // Refresh if missing or < 60 seconds before expiry
  if (!cachedToken || now > tokenExpiry - 60_000) {
    try {
      const res = await fetch("/api/token");
      if (!res.ok) return null;
      const { token } = await res.json() as { token: string };
      cachedToken  = token;
      tokenExpiry  = now + 4 * 60 * 1000; // 4-minute cache (token lives 5 min)
    } catch {
      return null;
    }
  }
  return cachedToken;
}

/** Clear token cache on sign-out */
export function clearApiToken() {
  cachedToken = null;
  tokenExpiry  = 0;
}

/**
 * Authenticated fetch to FastAPI.
 * `path` should start with "/" e.g. "/api/v1/clients"
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return fetch(`${API}${path}`, { ...init, headers });
}
