// Static reference map of plan capabilities (labels + limits) for display
// surfaces like the upgrade page. The AUTHORITATIVE, per-user source of truth is
// the live backend (see lib/entitlements.ts + lib/useEntitlements.ts) — do not
// gate behaviour off a global/build-time value here.

export type PlanId = "free" | "pro" | "custom";

type PlanEntitlements = {
  label: string;
  maxClients: number | null; // null = unlimited (custom, per-seat billed)
  usesManagedKeys: boolean;
  rawArtifactExport: boolean;
  perSeat?: boolean;
};

export const PLAN_ENTITLEMENTS: Record<PlanId, PlanEntitlements> = {
  free: {
    label: "Free",
    maxClients: 1,
    usesManagedKeys: false,
    rawArtifactExport: false,
  },
  pro: {
    label: "Pro",
    maxClients: 1,
    usesManagedKeys: true,
    rawArtifactExport: true,
  },
  custom: {
    label: "Custom",
    maxClients: null,
    usesManagedKeys: true,
    rawArtifactExport: true,
    perSeat: true,
  },
};

export const PRO_UPGRADE_HREF = "/dashboard/upgrade?feature=exports";
