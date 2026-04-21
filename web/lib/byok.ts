/**
 * BYOK — Bring Your Own Key
 *
 * Keys live ONLY in sessionStorage (browser tab memory).
 * They are NEVER written to localStorage, cookies, or our servers.
 * Closing the tab clears them permanently.
 *
 * sessionStorage key format: byok_key_<provider>
 * localStorage hint format:  byok_hint_<provider>  (boolean only — no key data)
 */

export type Provider = "openai" | "claude" | "perplexity" | "gemini";

export const PROVIDERS: Provider[] = ["openai", "claude", "perplexity", "gemini"];

const SESSION_PREFIX = "byok_key_";
const HINT_PREFIX    = "byok_hint_";

// ── Write ─────────────────────────────────────────────────────────────────────

/** Save a key to sessionStorage. Writes a non-sensitive hint to localStorage. */
export function setKey(provider: Provider, key: string): void {
  if (typeof window === "undefined") return;
  const trimmed = key.trim();
  if (!trimmed) {
    clearKey(provider);
    return;
  }
  sessionStorage.setItem(`${SESSION_PREFIX}${provider}`, trimmed);
  // Hint: non-sensitive boolean flag so UI knows a key was set on last session
  localStorage.setItem(`${HINT_PREFIX}${provider}`, "1");
}

// ── Read ──────────────────────────────────────────────────────────────────────

/** Get the key for a provider (from sessionStorage). Returns null if missing. */
export function getKey(provider: Provider): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(`${SESSION_PREFIX}${provider}`);
}

/** Returns all currently set keys as a plain object (omits providers with no key). */
export function getAllKeys(): Partial<Record<Provider, string>> {
  const result: Partial<Record<Provider, string>> = {};
  for (const p of PROVIDERS) {
    const k = getKey(p);
    if (k) result[p] = k;
  }
  return result;
}

/** Returns true if at least one provider key is set in the current session. */
export function hasAnyKey(): boolean {
  return PROVIDERS.some((p) => Boolean(getKey(p)));
}

/** Returns true if key is set for a provider in current session. */
export function hasKey(provider: Provider): boolean {
  return Boolean(getKey(provider));
}

// ── Hint (localStorage — non-sensitive) ───────────────────────────────────────

/**
 * Returns true if a key was set in a previous session.
 * The actual key is gone — this just signals "you had this configured".
 */
export function hadKeyPreviousSession(provider: Provider): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(`${HINT_PREFIX}${provider}`) === "1";
}

/** Returns which providers had keys in the last session (hint only). */
export function getPreviousSessionHints(): Provider[] {
  return PROVIDERS.filter(hadKeyPreviousSession);
}

// ── Clear ─────────────────────────────────────────────────────────────────────

/** Remove a single provider's key (session + hint). */
export function clearKey(provider: Provider): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(`${SESSION_PREFIX}${provider}`);
  localStorage.removeItem(`${HINT_PREFIX}${provider}`);
}

/** Remove all provider keys (session + hints). */
export function clearAllKeys(): void {
  PROVIDERS.forEach(clearKey);
}
