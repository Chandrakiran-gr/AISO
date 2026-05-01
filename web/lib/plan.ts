export type PlanId = "free" | "pro" | "agency";

type PlanEntitlements = {
  label: string;
  maxClients: number | null;
  rawArtifactExport: boolean;
};

export const PLAN_ENTITLEMENTS: Record<PlanId, PlanEntitlements> = {
  free: {
    label: "Free",
    maxClients: 1,
    rawArtifactExport: false,
  },
  pro: {
    label: "Pro",
    maxClients: 5,
    rawArtifactExport: true,
  },
  agency: {
    label: "Agency",
    maxClients: null,
    rawArtifactExport: true,
  },
};

export const PRO_UPGRADE_HREF = "/dashboard/upgrade?feature=exports";
const DEFAULT_ARTIFACT_ACCESS_EMAILS = ["admin@aisoglobal.com"];

function normalizePlan(value: string | undefined): PlanId {
  const plan = value?.toLowerCase();
  if (plan === "pro" || plan === "agency") return plan;
  return "free";
}

function artifactAccessEmails(): Set<string> {
  const configured = (process.env.NEXT_PUBLIC_AISO_ARTIFACT_ACCESS_EMAILS ?? "")
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean);
  return new Set([...DEFAULT_ARTIFACT_ACCESS_EMAILS, ...configured]);
}

export const CURRENT_PLAN = normalizePlan(process.env.NEXT_PUBLIC_AISO_PLAN);

export function canAccessRawArtifacts(plan: PlanId, email?: string | null): boolean {
  if (PLAN_ENTITLEMENTS[plan].rawArtifactExport) return true;
  const normalizedEmail = email?.trim().toLowerCase();
  return Boolean(normalizedEmail && artifactAccessEmails().has(normalizedEmail));
}
