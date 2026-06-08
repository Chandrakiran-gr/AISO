// Live, per-user tier + entitlements fetched from the backend through the
// authenticated proxy (which injects X-User-Id). Tier can change via
// admin/billing, so this is always read fresh (never cached) — see useEntitlements.

export type PlanTier = "free" | "pro" | "custom";
export type BillingModel = "none" | "flat" | "per_seat";

export type Entitlements = {
  user_id: string;
  email: string;
  plan_tier: PlanTier;
  account_role: "user" | "admin";
  max_clients: number | null; // null = unlimited (custom)
  uses_managed_keys: boolean; // false only for free (BYOK)
  business_count: number;
  billing_model: BillingModel;
  can_download_artifacts: boolean;
  can_view_full_citations: boolean;
  can_view_source_graph: boolean;
};

export async function fetchEntitlements(): Promise<Entitlements> {
  const res = await fetch("/api/proxy/v1/auth/me", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to load entitlements (${res.status})`);
  }
  return (await res.json()) as Entitlements;
}

// ── Pure gate helpers (null = entitlements not yet loaded) ────────────────────

/** Free tier must bring its own keys; pro/custom run on managed server keys. */
export function requiresBYOK(e: Entitlements | null): boolean {
  return !!e && !e.uses_managed_keys;
}

/** True when the user has hit their plan's business cap (custom = unlimited). */
export function atBusinessLimit(e: Entitlements | null): boolean {
  return !!e && e.max_clients !== null && e.business_count >= e.max_clients;
}

/**
 * Raw-artifact export gate. While entitlements are still loading we treat it as
 * unlocked to avoid a locked-state flash; the backend independently enforces the
 * 403 on the actual download, so this is UX only.
 */
export function canAccessRawArtifacts(e: Entitlements | null): boolean {
  return e ? e.can_download_artifacts : true;
}
