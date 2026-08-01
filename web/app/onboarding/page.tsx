"use client";

import { useState, useEffect, useLayoutEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import styles from "./onboarding.module.css";
import { setKey, getKey, getAllKeys, hadKeyPreviousSession, clearKey, type Provider } from "@/lib/byok";
import { INTENT_GROUPS } from "@/lib/intent-groups";
import { useEntitlements } from "@/lib/useEntitlements";

const PROVIDERS: { id: Provider; name: string; color: string }[] = [
  { id: "openai",     name: "ChatGPT",    color: "#10a37f" },
  { id: "claude",     name: "Claude",     color: "#e8b68a" },
  { id: "perplexity", name: "Perplexity", color: "#1fb8cd" },
  { id: "gemini",     name: "Gemini",     color: "#4285f4" },
];

const GROUPS = INTENT_GROUPS;

const STEPS = [
  { num: 1, label: "Business" },
  { num: 2, label: "Discover" },
  { num: 3, label: "Review" },
  { num: 4, label: "Prompts" },
  { num: 5, label: "Launch" },
];

const REVIEW_PROMPT_COUNT = 45;

const SCAN_STEPS = [
  "Preparing confirmed client profile...",
  "Generating context-aware question bank...",
  "Querying selected AI platforms...",
  "Analysing brand mentions...",
  "Computing visibility score...",
];

const SCAN_OBJECTIVES = [
  { id: "high_intent_visibility", label: "Improve high-intent buyer visibility" },
  { id: "find_competitor_gaps", label: "Find why AI recommends competitors" },
  { id: "local_discovery_visibility", label: "Improve local discovery visibility" },
  { id: "trust_citation_proof", label: "Improve trust, reviews, and citation proof" },
  { id: "new_market_service_audience", label: "Validate a new market, service, or audience" },
] as const;

const PIPELINE_OBJECTIVES = [
  {
    id: "awareness",
    label: "Awareness building",
    help: "Use this when you want AI answers to introduce your business, category, or market to people who are still learning what options exist.",
  },
  {
    id: "consideration",
    label: "Consideration",
    help: "Use this when customers already know the category and are comparing approaches, vendors, stores, products, or providers.",
  },
  {
    id: "preference",
    label: "Preference / displacement",
    help: "Use this when you want to understand whether AI answers prefer you over alternatives and what proof would shift that recommendation.",
  },
  {
    id: "reputation_defense",
    label: "Reputation defense",
    help: "Use this when trust, risk, reviews, compliance, or public perception are central to how customers evaluate you.",
  },
  {
    id: "competitive_intelligence",
    label: "Competitive intelligence",
    help: "Use this when the scan should emphasize why AI tools mention competitors, substitutes, marketplaces, or incumbent options.",
  },
] as const;

type VerticalOption = {
  id: string;
  label: string;
  description: string;
  example?: string | null;
};

interface FormState {
  businessName: string;
  websiteUrl: string;
  vertical: string;
  pipelineObjective: string;
  industry: string;
  location: string;
  competitors: string;
  intake: Record<string, string>;
  providers: string[];
  groups: string[];
  customQuestions: string[];
}

const DEFAULT: FormState = {
  businessName: "",
  websiteUrl: "",
  vertical: "",
  pipelineObjective: "preference",
  industry: "",
  location: "",
  competitors: "",
  intake: {},
  providers: ["openai", "claude", "perplexity", "gemini"],
  groups: GROUPS.map((group) => group.id),
  customQuestions: [],
};

// A single review prompt the user sees and edits before launching a scan.
// "branded" names the brand; "category" is category-level with no brand.
type PromptKind = "branded" | "category";
interface ReviewPrompt {
  text: string;
  kind: PromptKind;
  journey_stage?: string;
  brand_frame?: string;
}

type IntakeField = {
  id: string;
  label: string;
  type: "text" | "textarea" | "select" | "list" | string;
  required: boolean;
  hint?: string | null;
  placeholder?: string | null;
  patch_field: string;
  options: string[];
  validators: { min_items?: number };
};

type IntakeSchema = {
  vertical: string;
  label: string;
  description: string;
  required_fields: string[];
  fields: IntakeField[];
};

type ExistingClient = {
  id: string;
  name: string;
  url: string;
  industry: string | null;
  location: string | null;
  competitors: string[] | null;
};

type BusinessProfileData = {
  onboarding_id: string;
  client_id: string;
  vertical: string;
  objective: string;
  category: string;
  icp: Record<string, unknown>;
  geographic_scope: Record<string, unknown>;
  competitors: string[];
  personas: Record<string, unknown>;
  crawl_artifacts: Record<string, unknown>;
  floor_met: boolean;
  missing_fields: string[];
  onboarding_completed_at?: string | null;
  founder_reviewed_at?: string | null;
};

type ContextItem = {
  name: string;
  type?: string;
  confidence?: number;
  source_url?: string;
  price?: string;
  duration?: string;
  description?: string;
  group?: string;
  bookable?: boolean;
  usage?: string;
};

type ScanObjective = {
  objective?: string;
  label?: string;
  optimization_objectives?: string[];
  custom_objective?: string;
  custom?: string;
  source_url?: string;
  confidence?: number;
};

type BuyerContext = {
  label: string;
  audience_type?: string;
  problem?: string;
  desired_outcome?: string;
  trigger_event?: string;
  constraints?: string;
  decision_criteria?: string;
  priority?: "high" | "medium" | "low" | string;
  source_url?: string;
  confidence?: number;
};

type ContextProfile = {
  version?: string;
  business: {
    name: string;
    type?: string;
    confidence?: number;
    source_url?: string;
    website_url?: string;
  };
  categories: ContextItem[];
  offering_groups: ContextItem[];
  offerings: ContextItem[];
  product_brands: ContextItem[];
  competitors: ContextItem[];
  locations: {
    physical_locations: ContextItem[];
    service_areas: ContextItem[];
    visibility_markets: ContextItem[];
    excluded_locations: ContextItem[];
  };
  goals: ContextItem[];
  personas: ContextItem[];
  scan_objective?: ScanObjective;
  buyer_contexts?: BuyerContext[];
  differentiators: ContextItem[];
  guardrails: string[];
};

type ClientContextData = {
  client_id: string;
  status: "not_started" | "discovering" | "draft" | "confirmed" | "needs_review" | "failed" | string;
  profile_json: ContextProfile | null;
  evidence_json: { page_count?: number; pages?: unknown[]; warnings?: string[]; profile_draft?: { field_sources?: Record<string, string> } } | null;
  warnings_json: string[];
};

type CrawlJobData = {
  job_id: string;
  status: string;
  pages_discovered: number;
  pages_crawled: number;
  pages_skipped: number;
  pages_failed: number;
  warnings: string[];
  error_message?: string | null;
};

type ActionStatus = "idle" | "loading" | "error";

const API = "/api/proxy";
const DISCOVERY_POLL_MS = 1500;
const DISCOVERY_MAX_POLLS = 60;

function providerName(id: string): string {
  return PROVIDERS.find((provider) => provider.id === id)?.name ?? id;
}

function missingSelectedProviderKeys(providerIds: string[]): Provider[] {
  return providerIds
    .filter((id): id is Provider => PROVIDERS.some((provider) => provider.id === id))
    .filter((id) => !getKey(id));
}

function parseCompetitors(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 10);
}

function splitListValue(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function fieldValue(form: FormState, fieldId: string): string {
  return form.intake[fieldId] ?? "";
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function storedValueToInput(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean).join("\n");
  }
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value).trim();
}

function businessProfileValueForPatchField(profile: BusinessProfileData, patchField: string): unknown {
  const firmographics = recordValue(profile.icp.firmographics);
  switch (patchField) {
    case "category":
      return profile.category;
    case "competitors":
      return profile.competitors;
    case "industry":
      return firmographics.industry;
    case "employee_band":
      return firmographics.employee_band;
    case "revenue_band":
      return firmographics.revenue_band;
    case "firmographic_geography":
    case "icp_geography":
      return firmographics.geography;
    case "primary_persona":
      return profile.personas.primary;
    case "economic_buyer":
      return profile.personas.economic_buyer;
    case "end_user":
      return profile.personas.end_user;
    case "nap":
      return profile.geographic_scope.nap;
    case "service_radius":
      return profile.geographic_scope.service_radius;
    case "hours":
      return profile.geographic_scope.hours;
    case "geographic_scope_description":
      return profile.geographic_scope.description;
    case "jurisdictions":
      return profile.geographic_scope.jurisdictions;
    case "shipping_geographic_scope":
    case "shipping_scope":
      return profile.geographic_scope.shipping;
    default:
      return profile.icp[patchField];
  }
}

function intakeFromBusinessProfile(profile: BusinessProfileData, schema: IntakeSchema): Record<string, string> {
  const intake: Record<string, string> = {};
  for (const field of schema.fields) {
    const value = storedValueToInput(businessProfileValueForPatchField(profile, field.patch_field));
    if (value) intake[field.id] = value;
  }
  return intake;
}

function firstPresentProfileValue(profile: BusinessProfileData, patchFields: string[]): string {
  for (const patchField of patchFields) {
    const value = storedValueToInput(businessProfileValueForPatchField(profile, patchField));
    if (value) return value;
  }
  return "";
}

function formFromExistingProfile(client: ExistingClient, profile: BusinessProfileData, schema: IntakeSchema): FormState {
  const intake = intakeFromBusinessProfile(profile, schema);
  const withStoredFields: FormState = {
    ...DEFAULT,
    businessName: client.name,
    websiteUrl: client.url,
    vertical: profile.vertical,
    pipelineObjective: profile.objective || DEFAULT.pipelineObjective,
    intake,
    industry: profile.category || client.industry || firstPresentProfileValue(profile, ["industry", "brand_archetype", "target"]),
    location: client.location || firstPresentProfileValue(profile, [
      "geographic_scope_description",
      "shipping_geographic_scope",
      "service_radius",
      "firmographic_geography",
      "jurisdictions",
    ]),
    competitors: profile.competitors?.length ? profile.competitors.join(", ") : client.competitors?.join(", ") ?? "",
  };
  return legacyFormFromIntake(withStoredFields, schema);
}

function primaryLocationFromIntake(form: FormState): string {
  return (
    form.intake.geographic_scope_description
    || form.intake.shipping_geographic_scope
    || form.intake.service_radius
    || form.intake.firmographic_geography
    || form.location
    || ""
  ).trim();
}

function legacyFormFromIntake(form: FormState, schema: IntakeSchema | null): FormState {
  const fields = schema?.fields ?? [];
  const categoryField = fields.find((field) => field.patch_field === "category");
  const competitorsField = fields.find((field) => field.patch_field === "competitors");
  return {
    ...form,
    industry: (categoryField ? fieldValue(form, categoryField.id) : form.industry).trim(),
    location: primaryLocationFromIntake(form),
    competitors: (competitorsField ? fieldValue(form, competitorsField.id) : form.competitors).trim(),
  };
}

function validateIntake(_form: FormState, schema: IntakeSchema | null): string[] {
  if (!_form.vertical.trim()) return ["Choose your business type."];
  if (!schema) return ["Business type details are still loading."];
  // Intake fields are optional now: AISO drafts your business details from the
  // site after the crawl and you confirm them, so name + URL + type is enough.
  return [];
}

function buildIntakePatch(form: FormState, schema: IntakeSchema): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  for (const field of schema.fields) {
    const raw = fieldValue(form, field.id).trim();
    if (!raw) continue;
    const parsed = field.type === "list" ? splitListValue(raw) : raw;
    patch[field.patch_field] = field.patch_field === "category" && Array.isArray(parsed)
      ? parsed.join(", ")
      : parsed;
  }
  return patch;
}

function competitorNamesFromProfile(profile: ContextProfile): string[] {
  return profile.competitors.map((item) => item.name.trim()).filter(Boolean);
}

function defaultScanObjective(): ScanObjective {
  return {
    objective: "",
    label: "",
    optimization_objectives: [],
    custom_objective: "",
    custom: "",
    source_url: "manual_onboarding",
    confidence: 0.9,
  };
}

function validObjectiveIds(values: unknown): string[] {
  const ids = new Set<string>(SCAN_OBJECTIVES.map((objective) => objective.id));
  const source = Array.isArray(values) ? values : [];
  const selected: string[] = [];
  for (const value of source) {
    if (typeof value !== "string" || !ids.has(value) || selected.includes(value)) continue;
    selected.push(value);
  }
  return selected;
}

function objectiveLabel(id: string): string {
  return SCAN_OBJECTIVES.find((objective) => objective.id === id)?.label ?? id;
}

function selectedObjectiveIds(scanObjective?: ScanObjective): string[] {
  const selected = validObjectiveIds(scanObjective?.optimization_objectives);
  if (selected.length > 0) return selected;
  return validObjectiveIds(scanObjective?.objective ? [scanObjective.objective] : []);
}

function objectiveSummary(scanObjective?: ScanObjective): string {
  const selected = selectedObjectiveIds(scanObjective);
  if (selected.length > 0) return selected.map(objectiveLabel).join(", ");
  if ((scanObjective?.custom_objective ?? scanObjective?.custom ?? "").trim()) return "Custom objective";
  return "No template selected";
}

function businessTypeOption(id: string, options: VerticalOption[]) {
  return options.find((option) => option.id === id);
}

function pipelineObjectiveOption(id: string) {
  return PIPELINE_OBJECTIVES.find((option) => option.id === id);
}

function compactHelp(...parts: Array<string | null | undefined>): string {
  return parts.map((part) => part?.trim()).filter(Boolean).join(" ");
}

function optionHelp(title: string | undefined, body: string | null | undefined, example?: string | null): string {
  return compactHelp(title ? `${title}:` : null, body, example);
}

function InfoCue({ id, text }: { id: string; text: string }) {
  return (
    <span className={styles.infoCue} tabIndex={0} aria-describedby={id} aria-label={text}>
      ?
      <span id={id} role="tooltip" className={styles.infoBubble}>{text}</span>
    </span>
  );
}

function scanObjectiveFromSelection(objectives: string[], customObjective: string): ScanObjective {
  const selected = validObjectiveIds(objectives);
  const cleanCustom = customObjective.slice(0, 500);
  return {
    objective: selected[0] ?? "",
    label: selected.map(objectiveLabel).join(", "),
    optimization_objectives: selected,
    custom_objective: cleanCustom,
    custom: cleanCustom,
    source_url: "manual_onboarding",
    confidence: 0.9,
  };
}

function normalizedScanObjective(scanObjective?: ScanObjective): ScanObjective {
  return scanObjectiveFromSelection(
    selectedObjectiveIds(scanObjective),
    scanObjective?.custom_objective ?? scanObjective?.custom ?? "",
  );
}

function buyerContextIsUsable(context: BuyerContext): boolean {
  return Boolean(
    context.label?.trim()
    && [context.problem, context.desired_outcome, context.constraints, context.decision_criteria].some((value) => value?.trim()),
  );
}

function normalizedProfile(profile: ContextProfile): ContextProfile {
  const scanObjective = normalizedScanObjective(profile.scan_objective ?? defaultScanObjective());
  const sourceBuyerContexts = Array.isArray(profile.buyer_contexts) ? profile.buyer_contexts : [];
  const buyerContexts = sourceBuyerContexts
    .filter(buyerContextIsUsable)
    .map((context) => ({
      ...context,
      priority: context.priority || "medium",
      source_url: context.source_url || "manual_onboarding",
      confidence: typeof context.confidence === "number" ? context.confidence : 0.9,
    }));
  return {
    ...profile,
    categories: normalizeContextItems(profile.categories),
    offering_groups: normalizeContextItems(profile.offering_groups),
    offerings: normalizeContextItems(profile.offerings),
    product_brands: normalizeContextItems(profile.product_brands),
    competitors: normalizeContextItems(profile.competitors),
    locations: {
      physical_locations: normalizeContextItems(profile.locations?.physical_locations),
      service_areas: normalizeContextItems(profile.locations?.service_areas),
      visibility_markets: normalizeContextItems(profile.locations?.visibility_markets),
      excluded_locations: normalizeContextItems(profile.locations?.excluded_locations),
    },
    goals: normalizeContextItems(profile.goals),
    personas: normalizeContextItems(profile.personas),
    differentiators: normalizeContextItems(profile.differentiators),
    guardrails: normalizeGuardrails(profile.guardrails),
    scan_objective: {
      ...scanObjective,
      label: objectiveSummary(scanObjective),
      custom_objective: scanObjective.custom_objective ?? scanObjective.custom ?? "",
      custom: scanObjective.custom_objective ?? scanObjective.custom ?? "",
    },
    buyer_contexts: buyerContexts,
  };
}

function emptyProfile(form: FormState): ContextProfile {
  const competitors = parseCompetitors(form.competitors).map((name) => manualItem(name, "competitor_business"));
  const locations = form.location ? [manualItem(form.location, "visibility_market", { usage: "visibility_only" })] : [];
  return {
    version: "client_context.v1",
    business: {
      name: form.businessName,
      type: "business",
      confidence: 0.8,
      source_url: "manual_onboarding",
      website_url: form.websiteUrl,
    },
    categories: form.industry ? [manualItem(form.industry, "category")] : [],
    offering_groups: [],
    offerings: [],
    product_brands: [],
    competitors,
    locations: {
      physical_locations: [],
      service_areas: [],
      visibility_markets: locations,
      excluded_locations: [],
    },
    goals: [manualItem(`Evaluate the right ${form.industry.trim() || "option"}`, "goal")],
    personas: [manualItem("Target customers", "persona")],
    scan_objective: defaultScanObjective(),
    buyer_contexts: [],
    differentiators: [],
    guardrails: [
      "Do not compare product brands as competitors.",
      "Do not treat offering groups as bookable services unless explicitly marked bookable.",
      "Do not use visibility-only markets for urgent purchase or availability prompts.",
    ],
  };
}

function manualItem(name: string, type: string, extra: Partial<ContextItem> = {}): ContextItem {
  return {
    name,
    type,
    confidence: 0.9,
    source_url: "manual_onboarding",
    ...extra,
  };
}

function normalizeTextValue(value: string): string {
  return value.trim();
}

function normalizeContextItems(items: ContextItem[] | undefined): ContextItem[] {
  const seen = new Set<string>();
  return (items ?? [])
    .map((item) => ({ ...item, name: normalizeTextValue(item.name) }))
    .filter((item) => {
      if (!item.name) return false;
      const fingerprint = `${item.type}:${item.name.toLowerCase()}`;
      if (seen.has(fingerprint)) return false;
      seen.add(fingerprint);
      return true;
    });
}

function normalizeGuardrails(guardrails: string[] | undefined): string[] {
  return Array.from(new Set((guardrails ?? []).map(normalizeTextValue).filter(Boolean)));
}

function contextMatchesForm(context: ClientContextData | null, form: FormState, clientId: string): boolean {
  if (context?.status !== "confirmed" || context.client_id !== clientId || !context.profile_json) {
    return false;
  }
  const contextUrl = context.profile_json.business?.website_url ?? "";
  return contextUrl.trim().toLowerCase() === form.websiteUrl.trim().toLowerCase();
}

async function readApiError(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    if (data?.detail?.error && Array.isArray(data.detail.missing_fields)) {
      return `${data.detail.error}: ${data.detail.missing_fields.join(", ")}`;
    }
    if (Array.isArray(data?.detail)) return data.detail.map((item: unknown) => String(item)).join(", ");
  } catch {
    // Keep fallback.
  }
  return fallback;
}

function isApprovedCrawlerProfileConflict(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return message.includes("profile is 'approved'") || message.includes("profile is already 'approved'");
}

async function getIntakeVerticals(): Promise<VerticalOption[]> {
  const res = await fetch(`${API}/v1/onboarding/intake-verticals`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to load business types (${res.status})`));
  return res.json();
}

async function getIntakeSchema(vertical: string): Promise<IntakeSchema> {
  const res = await fetch(`${API}/v1/onboarding/intake-schemas/${vertical}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to load intake schema (${res.status})`));
  return res.json();
}

async function startPipelineOnboarding(
  form: FormState,
  schema: IntakeSchema,
  clientId: string | null,
): Promise<ExistingClient> {
  const res = await fetch(`${API}/v1/onboarding/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      // Bind to the existing business so a re-scan updates it in place and never
      // creates a duplicate profile. Null only for a brand-new first business.
      client_id: clientId,
      display_name: form.businessName,
      url: form.websiteUrl,
      vertical: form.vertical,
      objective: form.pipelineObjective,
      category: form.industry || null,
    }),
  });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to start onboarding (${res.status})`));
  const started = await res.json();
  const onboardingId = started.onboarding_id as string;

  const patch = buildIntakePatch(form, schema);
  const patchRes = await fetch(`${API}/v1/onboarding/${onboardingId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!patchRes.ok) throw new Error(await readApiError(patchRes, `Failed to save intake (${patchRes.status})`));

  const submitRes = await fetch(`${API}/v1/onboarding/${onboardingId}/submit`, { method: "POST" });
  if (!submitRes.ok) throw new Error(await readApiError(submitRes, `Minimum context floor failed (${submitRes.status})`));

  return {
    id: started.client_id,
    name: started.client_name,
    url: started.client_url,
    industry: form.industry,
    location: form.location,
    competitors: parseCompetitors(form.competitors),
  };
}

async function getClientContext(clientId: string): Promise<ClientContextData | null> {
  const res = await fetch(`${API}/v1/clients/${clientId}/context`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

async function getOnboardingProfile(clientId: string): Promise<BusinessProfileData | null> {
  const res = await fetch(`${API}/v1/onboarding/${clientId}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function createCrawlerWorkspace(clientId: string, websiteUrl: string): Promise<{ workspace_id: string }> {
  const res = await fetch(`${API}/v1/onboarding-workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: clientId,
      website_url: websiteUrl,
      consent_confirmed: true,
    }),
  });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to create discovery workspace (${res.status})`));
  return res.json();
}

async function createCrawlJob(workspaceId: string): Promise<CrawlJobData> {
  const res = await fetch(`${API}/v1/onboarding-workspaces/${workspaceId}/crawl-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ crawl_mode: "standard", max_pages: 25, max_depth: 3 }),
  });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to start website discovery (${res.status})`));
  return res.json();
}

async function getCrawlJob(jobId: string): Promise<CrawlJobData> {
  const res = await fetch(`${API}/v1/crawl-jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to poll website discovery (${res.status})`));
  return res.json();
}

async function editCrawlerBusinessProfile(workspaceId: string, profile: ContextProfile): Promise<void> {
  const locations = [
    ...profile.locations.physical_locations,
    ...profile.locations.service_areas,
    ...profile.locations.visibility_markets,
  ].map((item) => item.name);
  const res = await fetch(`${API}/v1/onboarding-workspaces/${workspaceId}/business-profile`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      company_name: profile.business.name,
      industry: profile.categories[0]?.name ?? null,
      products: profile.product_brands.map((item) => item.name),
      services: profile.offerings.map((item) => item.name),
      locations,
    }),
  });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to save reviewed crawler profile (${res.status})`));
}

async function approveCrawlerBusinessProfile(workspaceId: string): Promise<void> {
  const res = await fetch(`${API}/v1/onboarding-workspaces/${workspaceId}/approve`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to approve crawler profile (${res.status})`));
}

async function saveClientContext(clientId: string, profile: ContextProfile, warnings: string[]): Promise<ClientContextData> {
  const res = await fetch(`${API}/v1/clients/${clientId}/context`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      status: "confirmed",
      profile_json: profile,
      warnings_json: warnings,
    }),
  });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to confirm client context (${res.status})`));
  return res.json();
}

async function confirmPipelineBusinessProfile(clientId: string, profile: ContextProfile): Promise<void> {
  const res = await fetch(`${API}/v1/onboarding/${clientId}/confirm-profile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      category: profile.categories[0]?.name ?? "",
      competitors: competitorNamesFromProfile(profile),
      primary_persona: profile.personas[0]?.name ?? undefined,
    }),
  });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to confirm business profile (${res.status})`));
}

async function generatePrompts(
  clientId: string,
  variation: number,
): Promise<{ branded: ReviewPrompt[]; category: ReviewPrompt[]; model: string }> {
  const res = await fetch(`${API}/v1/onboarding/${clientId}/generate-prompts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ final_count: REVIEW_PROMPT_COUNT, variation }),
  });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to generate prompts (${res.status})`));
  const data = await res.json();
  const tag = (list: ReviewPrompt[] | undefined, kind: PromptKind) =>
    (list ?? []).map((p) => ({ ...p, kind }));
  return {
    branded: tag(data.branded, "branded"),
    category: tag(data.category, "category"),
    model: typeof data.model === "string" ? data.model : "",
  };
}

interface DraftedFields {
  description: string;
  industry: string;
  audiences: string[];
  competitors: string[];
}

async function draftFields(clientId: string, variation = 0): Promise<DraftedFields & { provider: string; model: string }> {
  const res = await fetch(`${API}/v1/onboarding/${clientId}/draft-fields`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ variation }),
  });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to draft business fields (${res.status})`));
  const d = await res.json();
  return {
    description: typeof d.description === "string" ? d.description : "",
    industry: typeof d.industry === "string" ? d.industry : "",
    audiences: Array.isArray(d.audiences) ? d.audiences.map(String) : [],
    competitors: Array.isArray(d.competitors) ? d.competitors.map(String) : [],
    provider: typeof d.provider === "string" ? d.provider : "",
    model: typeof d.model === "string" ? d.model : "",
  };
}

async function createScan(
  clientId: string,
  providers: string[],
  groups: string[],
  customQuestions: string[],
  prompts: ReviewPrompt[],
  byokKeys: Record<string, string>,
): Promise<string> {
  // When the user approved a prompt list, the scan runs exactly those (Phase 13
  // bypasses the slot-template generator). We also forward the texts as custom
  // questions so the legacy free-tier engine runs the same approved set.
  const approved = prompts
    .map((p) => ({ ...p, text: p.text.replace(/\s+/g, " ").trim() }))
    .filter((p) => p.text.length > 0);
  const hasPrompts = approved.length > 0;
  const res = await fetch(`${API}/v1/clients/${clientId}/scans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: clientId,
      providers,
      groups: hasPrompts ? [] : groups,
      custom_questions: hasPrompts ? approved.map((p) => p.text) : customQuestions,
      prompts: hasPrompts
        ? approved.map((p) => ({ text: p.text, journey_stage: p.journey_stage, brand_frame: p.brand_frame }))
        : undefined,
      byok_keys: Object.keys(byokKeys).length > 0 ? byokKeys : undefined,
    }),
  });
  if (!res.ok) {
    let message = `Failed to create scan (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") message = data.detail;
    } catch {
      // Keep status fallback.
    }
    throw new Error(message);
  }
  const data = await res.json();
  return data.id as string;
}

function normalizeCustomQuestion(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function validateCustomQuestions(values: string[]): { questions: string[]; error: string | null } {
  const questions: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const question = normalizeCustomQuestion(value);
    if (!question) continue;
    const key = question.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    questions.push(question);
  }
  return { questions, error: null };
}

async function pollScan(clientId: string, scanId: string): Promise<{
  status: string;
  skipped_providers?: string[];
  error?: string | null;
}> {
  const res = await fetch(`${API}/v1/clients/${clientId}/scans/${scanId}`);
  if (!res.ok) throw new Error(`Scan poll failed (${res.status})`);
  return res.json();
}

function Step1({
  form,
  set,
  verticalOptions,
  schema,
  verticalOptionsStatus,
  verticalOptionsError,
  schemaStatus,
  schemaError,
  onNext,
  status,
  error,
}: {
  form: FormState;
  set: (f: FormState) => void;
  verticalOptions: VerticalOption[];
  schema: IntakeSchema | null;
  verticalOptionsStatus: ActionStatus;
  verticalOptionsError: string | null;
  schemaStatus: ActionStatus;
  schemaError: string | null;
  onNext: () => void;
  status: ActionStatus;
  error: string | null;
}) {
  const intakeIssues = schemaStatus === "loading" ? ["Intake schema is still loading."] : validateIntake(form, schema);
  const valid = form.businessName.trim().length > 0 && form.websiteUrl.startsWith("http") && form.vertical.trim().length > 0 && intakeIssues.length === 0;
  const selectedBusinessType = businessTypeOption(form.vertical, verticalOptions);
  const selectedObjective = pipelineObjectiveOption(form.pipelineObjective);
  const verticalOptionsLoading = verticalOptionsStatus === "loading";
  const businessTypeHelp = selectedBusinessType
    ? optionHelp(selectedBusinessType.label, selectedBusinessType.description, selectedBusinessType.example)
    : "This routes the intake questions and question-generation logic. Choose the closest business model, then use the specific category fields for detail.";
  const objectiveHelp = selectedObjective
    ? optionHelp(selectedObjective.label, selectedObjective.help)
    : "This changes the mix of awareness, comparison, preference, reputation, and competitor questions AISO prioritizes.";
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (valid && status !== "loading") onNext(); }}>
      <span className={styles.stepBadge}>Step 1 of 5 · Business basics</span>
      <h2 className={styles.stepTitle}>Tell AISO which business to analyze</h2>
      <p className={styles.stepSubtitle}>
        Choose a vertical and complete the required context before AISO builds the question bank.
      </p>
      {error && <div className={styles.validationError} role="alert">{error}</div>}
      {verticalOptionsError && <div className={styles.validationError} role="alert">{verticalOptionsError}</div>}
      {schemaError && <div className={styles.validationError} role="alert">{schemaError}</div>}
      <div className={styles.fields}>
        <div className={styles.fieldGroup}>
          <label className={styles.label} htmlFor="ob-name">Business name *</label>
          <input
            id="ob-name"
            className="input"
            type="text"
            placeholder="Your business name"
            value={form.businessName}
            onChange={(e) => set({ ...form, businessName: e.target.value })}
            required
          />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.label} htmlFor="ob-url">Website URL *</label>
          <input
            id="ob-url"
            className="input"
            type="url"
            placeholder="https://yourbusiness.com"
            value={form.websiteUrl}
            onChange={(e) => set({ ...form, websiteUrl: e.target.value })}
            required
          />
        </div>
        <div className={styles.optionalGrid}>
          <div className={styles.fieldGroup}>
            <div className={styles.labelRow}>
              <label className={styles.label} htmlFor="ob-vertical">Business type *</label>
              <InfoCue
                id="ob-vertical-tip"
                text={businessTypeHelp}
              />
            </div>
            <select
              id="ob-vertical"
              className="input"
              value={form.vertical}
              onChange={(e) => set({ ...form, vertical: e.target.value, intake: {}, industry: "", location: "", competitors: "" })}
              required
              disabled={verticalOptionsLoading || verticalOptions.length === 0}
            >
              <option value="">{verticalOptionsLoading ? "Loading business types..." : "Choose your business type"}</option>
              {verticalOptions.map((vertical) => (
                <option key={vertical.id} value={vertical.id}>{vertical.label}</option>
              ))}
            </select>
          </div>
          <div className={styles.fieldGroup}>
            <div className={styles.labelRow}>
              <label className={styles.label} htmlFor="ob-objective">Measurement objective *</label>
              <InfoCue
                id="ob-objective-tip"
                text={objectiveHelp}
              />
            </div>
            <select
              id="ob-objective"
              className="input"
              value={form.pipelineObjective}
              onChange={(e) => set({ ...form, pipelineObjective: e.target.value })}
            >
              {PIPELINE_OBJECTIVES.map((objective) => (
                <option key={objective.id} value={objective.id}>{objective.label}</option>
              ))}
            </select>
          </div>
        </div>
        {intakeIssues.length > 0 && form.businessName && form.websiteUrl && (
          <div className={styles.warningPanel}>
            <strong>Required before continuing</strong>
            <span>{intakeIssues.join(", ")}</span>
          </div>
        )}
      </div>
      <div className={styles.navRow}>
        <div />
        <button type="submit" className={styles.nextBtn} disabled={!valid || status === "loading"} id="ob-step1-next">
          {status === "loading" ? "Saving..." : "Read my website"}
        </button>
      </div>
    </form>
  );
}

function Step2({
  context,
  discovering,
  error,
  onBack,
  onRetry,
  onManual,
  onNext,
}: {
  context: ClientContextData | null;
  discovering: boolean;
  error: string | null;
  onBack: () => void;
  onRetry: () => void;
  onManual: () => void;
  onNext: () => void;
}) {
  const pageCount = context?.evidence_json?.page_count ?? context?.evidence_json?.pages?.length ?? 0;
  const status = context?.status ?? (discovering ? "discovering" : "not_started");
  const isRunning = discovering || status === "discovering";
  const readyToReview = Boolean(context?.profile_json) && !isRunning && status !== "failed";
  return (
    <div>
      <span className={styles.stepBadge}>Step 2 of 5 · Website discovery</span>
      <h2 className={styles.stepTitle}>Reading public website evidence</h2>
      <p className={styles.stepSubtitle}>
        AISO only reads public pages. It does not log in, submit forms, make bookings, or collect private customer data.
      </p>

      <div className={styles.discoveryPanel}>
        <div className={isRunning ? styles.discoverySpinner : styles.discoveryMark}>
          {isRunning ? "" : "✓"}
        </div>
        <div>
          <strong>{isRunning ? "Discovering offerings, locations, proof, and calls to action" : "Discovery finished"}</strong>
          <p>
            {isRunning
              ? "This usually takes a few seconds for most public websites."
              : `${pageCount} public page${pageCount === 1 ? "" : "s"} reviewed. Continue to review and edit the extracted client context.`}
          </p>
        </div>
      </div>

      {readyToReview && (
        <div className={styles.reviewHint}>
          <strong>Extracted context is ready</strong>
          <span>The next step shows the discovered offerings, competitors, locations, audience segments, and proof signals before any scan runs.</span>
        </div>
      )}

      {error && <div className={styles.validationError} role="alert">{error}</div>}

      <div className={styles.navRow}>
        <button type="button" className={styles.backBtn} onClick={onBack}>Back</button>
        <div className={styles.navActions}>
          {!discovering && (
            <>
              <button type="button" className={styles.secondaryBtn} onClick={onRetry}>Refresh discovery</button>
              <button type="button" className={styles.secondaryBtn} onClick={onManual}>Enter manually</button>
            </>
          )}
          <button type="button" className={styles.nextBtn} onClick={onNext} disabled={!readyToReview}>
            Review extracted context
          </button>
        </div>
      </div>
    </div>
  );
}

function emptyDraftedFields(): DraftedFields {
  return { description: "", industry: "", audiences: [], competitors: [] };
}

function StepConfirm({
  fields,
  status,
  model,
  onChangeText,
  onChangeList,
  onRegenerate,
  onBack,
  onConfirm,
  saving,
  error,
}: {
  fields: DraftedFields;
  status: ActionStatus;
  model: string;
  onChangeText: (key: "description" | "industry", value: string) => void;
  onChangeList: (key: "audiences" | "competitors", values: string[]) => void;
  onRegenerate: () => void;
  onBack: () => void;
  onConfirm: () => void;
  saving: boolean;
  error: string | null;
}) {
  if (status === "loading") {
    return (
      <div className={styles.scanRunning}>
        <div className={styles.scanSpinner} />
        <div>
          <p className={styles.scanTitle}>Reading your website...</p>
          <p className={styles.scanCopy}>
            AISO is figuring out what you do, who you serve, and who you compete with. You can edit all of it next.
          </p>
        </div>
      </div>
    );
  }

  const listEditor = (key: "audiences" | "competitors", label: string, placeholder: string) => {
    const values = fields[key];
    return (
      <div className={styles.fieldGroup}>
        <div className={styles.labelRow}>
          <label className={styles.label}>{label}</label>
          <span className={styles.labelHint}>{values.length}</span>
        </div>
        <div className={styles.customQuestionPanel}>
          {values.length > 0 && (
            <div className={styles.customQuestionList}>
              {values.map((value, index) => (
                <div key={index} className={styles.customQuestionRow}>
                  <input
                    className="input"
                    value={value}
                    placeholder={placeholder}
                    onChange={(event) => onChangeList(key, values.map((v, i) => (i === index ? event.target.value : v)))}
                  />
                  <button
                    type="button"
                    className={styles.removeMiniBtn}
                    onClick={() => onChangeList(key, values.filter((_, i) => i !== index))}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
          <button type="button" className={styles.secondaryBtn} onClick={() => onChangeList(key, [...values, ""])}>
            Add {label.toLowerCase()}
          </button>
        </div>
      </div>
    );
  };

  const canConfirm = fields.description.trim().length > 0 && fields.industry.trim().length > 0;

  return (
    <div>
      <span className={styles.stepBadge}>Step 3 of 5 · Confirm your business</span>
      <h2 className={styles.stepTitle}>Here&apos;s what we understood</h2>
      <p className={styles.stepSubtitle}>
        AISO read your website and drafted this. Fix anything that&apos;s off - it shapes your prompts and scan. Empty? Just fill it in.
      </p>

      {status === "error" && (
        <div className={styles.validationError} role="alert">
          We couldn&apos;t read your site well - fill in the fields below, or{" "}
          <button type="button" className={styles.secondaryBtn} onClick={onRegenerate}>try again</button>.
        </div>
      )}
      {error && <div className={styles.validationError} role="alert">{error}</div>}

      <div className={styles.labelRow} style={{ marginBottom: "0.75rem" }}>
        <span className={styles.labelHint}>{model ? `AI-drafted · ${model}` : "AI-drafted"}</span>
        <button type="button" className={styles.secondaryBtn} onClick={onRegenerate}>Regenerate</button>
      </div>

      <div className={styles.fields}>
        <div className={styles.fieldGroup}>
          <label className={styles.label}>What you do</label>
          <textarea
            className={styles.customQuestionInput}
            style={{ minHeight: "6rem", width: "100%" }}
            value={fields.description}
            placeholder="What your business does and who it's for..."
            onChange={(event) => onChangeText("description", event.target.value)}
          />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.label}>Industry</label>
          <input
            className="input"
            value={fields.industry}
            placeholder="e.g. AI search optimization"
            onChange={(event) => onChangeText("industry", event.target.value)}
          />
        </div>
        {listEditor("audiences", "Who you serve", "e.g. marketing teams")}
        {listEditor("competitors", "Competitors", "e.g. a competitor brand")}
      </div>

      <div className={styles.navRow}>
        <button type="button" className={styles.backBtn} onClick={onBack}>Back</button>
        <button type="button" className={styles.nextBtn} onClick={onConfirm} disabled={saving || !canConfirm}>
          {saving ? "Saving..." : "Looks good, generate prompts"}
        </button>
      </div>
    </div>
  );
}

function StepPrompts({
  prompts,
  status,
  error,
  model,
  onUpdate,
  onRemove,
  onAdd,
  onRegenerate,
  onBack,
  onNext,
}: {
  prompts: ReviewPrompt[];
  status: ActionStatus;
  error: string | null;
  model: string;
  onUpdate: (index: number, text: string) => void;
  onRemove: (index: number) => void;
  onAdd: (kind: PromptKind) => void;
  onRegenerate: () => void;
  onBack: () => void;
  onNext: () => void;
}) {
  // Keep each prompt's index in the flat list so edit/remove target the right item.
  const indexed = prompts.map((prompt, index) => ({ prompt, index }));
  const category = indexed.filter((x) => x.prompt.kind === "category");
  const branded = indexed.filter((x) => x.prompt.kind === "branded");
  const usableCount = prompts.filter((p) => p.text.trim().length > 0).length;

  if (status === "loading") {
    return (
      <div className={styles.scanRunning}>
        <div className={styles.scanSpinner} />
        <div>
          <p className={styles.scanTitle}>Writing your prompts...</p>
          <p className={styles.scanCopy}>
            AISO is drafting the questions buyers ask AI assistants about your brand and category. You can edit everything next.
          </p>
        </div>
      </div>
    );
  }

  const renderList = (
    rows: { prompt: ReviewPrompt; index: number }[],
    kind: PromptKind,
  ) => (
    <div className={styles.fieldGroup}>
      <div className={styles.labelRow}>
        <label className={styles.label}>
          {kind === "branded" ? "Branded · your brand named" : "Category · no brand named"}
        </label>
        <span className={styles.labelHint}>{rows.length}</span>
      </div>
      <div className={styles.customQuestionPanel}>
        <p>
          {kind === "branded"
            ? "Questions that mention your brand by name (reviews, pricing, comparisons)."
            : "Category-level questions with no brand named. Most buyer discovery starts here."}
        </p>
        {rows.length > 0 && (
          <div className={styles.customQuestionList}>
            {rows.map(({ prompt, index }) => (
              <div key={index} className={styles.customQuestionRow}>
                <textarea
                  className={styles.customQuestionInput}
                  value={prompt.text}
                  placeholder={kind === "branded" ? "Add a branded question..." : "Add a category question..."}
                  onChange={(event) => onUpdate(index, event.target.value)}
                />
                <button type="button" className={styles.removeMiniBtn} onClick={() => onRemove(index)}>
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
        <button type="button" className={styles.secondaryBtn} onClick={() => onAdd(kind)}>
          Add {kind === "branded" ? "branded" : "category"} prompt
        </button>
      </div>
    </div>
  );

  return (
    <div>
      <span className={styles.stepBadge}>Step 4 of 5 · Review prompts</span>
      <h2 className={styles.stepTitle}>Review your search prompts</h2>
      <p className={styles.stepSubtitle}>
        These are the questions AISO will ask each AI assistant. Edit, add, or remove any of them - the scan runs exactly what you approve.
      </p>

      {status === "error" && (
        <div className={styles.validationError} role="alert">
          {error || "We could not generate prompts."}{" "}
          <button type="button" className={styles.secondaryBtn} onClick={onRegenerate}>Try again</button>
        </div>
      )}

      <div className={styles.labelRow} style={{ marginBottom: "0.75rem" }}>
        <span className={styles.labelHint}>
          {usableCount} prompt{usableCount === 1 ? "" : "s"} ready{model ? ` · ${model}` : ""}
        </span>
        <button type="button" className={styles.secondaryBtn} onClick={onRegenerate}>Regenerate all</button>
      </div>

      <div className={styles.fields}>
        {renderList(category, "category")}
        {renderList(branded, "branded")}
      </div>

      <div className={styles.navRow}>
        <button type="button" className={styles.backBtn} onClick={onBack}>Back</button>
        <button type="button" className={styles.nextBtn} onClick={onNext} disabled={usableCount === 0}>
          Continue to launch
        </button>
      </div>
    </div>
  );
}

function Step4({
  form,
  profile,
  set,
  promptCount,
  onBack,
  onLaunch,
  scanning,
  scanIdx,
  error,
  skipped,
  externalError,
  onClearExternalError,
  usesManagedKeys,
}: {
  form: FormState;
  profile: ContextProfile;
  set: (f: FormState) => void;
  promptCount: number;
  onBack: () => void;
  onLaunch: (customQuestions: string[]) => void;
  scanning: boolean;
  scanIdx: number;
  error: string | null;
  skipped: string[];
  externalError: string | null;
  onClearExternalError: () => void;
  usesManagedKeys: boolean;
}) {
  const [keysOpen, setKeysOpen] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [keySet, setKeySet] = useState<Partial<Record<Provider, boolean>>>({});
  const competitorCount = competitorNamesFromProfile(profile).length;
  const hasCompetitors = competitorCount > 0;

  function refreshKeyState() {
    const state: Partial<Record<Provider, boolean>> = {};
    for (const p of PROVIDERS) state[p.id] = Boolean(getKey(p.id));
    setKeySet(state);
    return state;
  }

  useEffect(() => {
    const timer = window.setTimeout(refreshKeyState, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (hasCompetitors || !form.groups.includes("G3")) return;
    const nextGroups = form.groups.filter((group) => group !== "G3");
    set({ ...form, groups: nextGroups.length ? nextGroups : ["G1"] });
  }, [form, hasCompetitors, set]);

  function handleKeyInput(provider: Provider, value: string) {
    const clean = value.trim();
    if (clean) {
      setKey(provider, clean);
      setKeySet((prev) => ({ ...prev, [provider]: true }));
      setValidationError(null);
      onClearExternalError();
      return;
    }
    clearKey(provider);
    setKeySet((prev) => ({ ...prev, [provider]: false }));
  }

  const toggleProvider = (id: string) => {
    const next = form.providers.includes(id) ? form.providers.filter((p) => p !== id) : [...form.providers, id];
    if (next.length > 0) {
      set({ ...form, providers: next });
      setValidationError(null);
      onClearExternalError();
    }
  };
  const toggleGroup = (id: string) => {
    if (id === "G3" && !hasCompetitors) {
      setValidationError("Add at least one competitor in Confirm context to enable G3 competitor coverage.");
      return;
    }
    const next = form.groups.includes(id) ? form.groups.filter((g) => g !== id) : [...form.groups, id];
    if (next.length > 0) {
      set({ ...form, groups: next });
      setValidationError(null);
    }
  };

  const selectedProviderKeysSet = form.providers.filter((id) => keySet[id as Provider]).length;
  const missingKeys = form.providers.filter((id) => !keySet[id as Provider]);
  const visibleValidationError = validationError ?? externalError;
  const byokPanelOpen = !usesManagedKeys && (keysOpen || missingKeys.length > 0 || Boolean(visibleValidationError));
  const providerNames = form.providers.map(providerName).join(", ");
  const customQuestionCount = validateCustomQuestions(form.customQuestions).questions.length;

  function updateCustomQuestion(index: number, value: string) {
    const next = [...form.customQuestions];
    next[index] = value;
    set({ ...form, customQuestions: next });
    setValidationError(null);
  }

  function addCustomQuestion() {
    set({ ...form, customQuestions: [...form.customQuestions, ""] });
    setValidationError(null);
  }

  function removeCustomQuestion(index: number) {
    set({ ...form, customQuestions: form.customQuestions.filter((_, i) => i !== index) });
    setValidationError(null);
  }

  function handleLaunchClick() {
    // The Prompts step defines the question set; skip the legacy group/custom-
    // question validation whenever an approved prompt list exists.
    if (promptCount === 0 && form.groups.includes("G3") && !hasCompetitors) {
      setValidationError("G3 needs at least one competitor. Add competitors in Confirm context or deselect G3.");
      return;
    }
    if (!usesManagedKeys) {
      const currentState = refreshKeyState();
      const missing = form.providers.filter((id) => !currentState[id as Provider]);
      if (missing.length > 0) {
        setKeysOpen(true);
        setValidationError(`Add API keys for selected providers: ${missing.map(providerName).join(", ")}.`);
        return;
      }
    }
    if (promptCount > 0) {
      setValidationError(null);
      onLaunch([]);
      return;
    }
    const customValidation = validateCustomQuestions(form.customQuestions);
    if (customValidation.error) {
      setValidationError(customValidation.error);
      return;
    }
    setValidationError(null);
    onLaunch(customValidation.questions);
  }

  if (scanning) {
    return (
      <div className={styles.scanRunning}>
        <div className={styles.scanSpinner} />
        <div>
          <p className={styles.scanTitle}>Running your scan...</p>
          <p className={styles.scanCopy}>AISO is using the confirmed profile to keep questions realistic and safe.</p>
        </div>
        <div className={styles.scanProgress}>
          <div className={styles.scanProgressTrack}>
            <div className={styles.scanProgressFill} />
          </div>
        </div>
        <p className={styles.scanStep}>{SCAN_STEPS[scanIdx]}</p>
      </div>
    );
  }

  return (
    <div>
      <span className={styles.stepBadge}>Step 5 of 5 · Configure and launch</span>
      <h2 className={styles.stepTitle}>Choose providers and launch</h2>
      <p className={styles.stepSubtitle}>
        BYOK keys are used only for this scan request. They are not saved to the database or written to logs.
      </p>
      {promptCount > 0 && (
        <div className={styles.infoPanel}>
          <strong>{promptCount} prompt{promptCount === 1 ? "" : "s"} ready</strong>
          <span>The scan will run the prompts you reviewed. Go back to Prompts to edit them.</span>
        </div>
      )}
      {error && <div className={styles.validationError} role="alert">{error}</div>}
      {skipped.length > 0 && (
        <div className={styles.warningPanel}>
          <strong>Skipped providers</strong>
          <span>{skipped.join(", ")}</span>
        </div>
      )}
      <div className={styles.fields}>
        <div className={styles.fieldGroup}>
          <label className={styles.label}>AI platforms to monitor</label>
          <div className={styles.providerGrid}>
            {PROVIDERS.map((p) => (
              <label key={p.id} className={styles.providerOption}>
                <input type="checkbox" checked={form.providers.includes(p.id)} onChange={() => toggleProvider(p.id)} />
                <span className={styles.providerDot} style={{ background: p.color }} />
                <span className={styles.providerName}>{p.name}</span>
                <span className={styles.checkIndicator}>✓</span>
              </label>
            ))}
          </div>
        </div>
        {promptCount === 0 && (
        <>
        <div className={styles.fieldGroup}>
          <div className={styles.labelRow}>
            <label className={styles.label}>Question intent groups</label>
            <span className={styles.labelHint}>{form.groups.length}/7 selected</span>
          </div>
          <div className={styles.groupTags}>
            {GROUPS.map((g) => {
              const disabled = g.id === "G3" && !hasCompetitors;
              const reduced = g.id === "G7" && !hasCompetitors;
              return (
                <button
                  key={g.id}
                  type="button"
                  title={disabled ? "Add competitors to enable this group." : reduced ? "Runs method and service comparisons without business head-to-head rows." : g.desc}
                  className={`${styles.groupTag} ${form.groups.includes(g.id) ? styles.selected : ""} ${disabled ? styles.disabledGroup : ""} ${reduced ? styles.reducedGroup : ""}`}
                  onClick={() => toggleGroup(g.id)}
                  disabled={disabled}
                >
                  <span>{g.id} · {g.label}</span>
                  {disabled && <small>Needs competitors</small>}
                  {reduced && <small>Reduced</small>}
                </button>
              );
            })}
          </div>
          {!hasCompetitors && (
            <div className={styles.infoPanel}>
              <strong>Competitor coverage is off</strong>
              <span>G3 is unavailable until competitors are added. G7 will still run method and service comparisons, but business-vs-business rows are skipped.</span>
            </div>
          )}
        </div>
        <div className={styles.fieldGroup}>
          <div className={styles.labelRow}>
            <label className={styles.label}>Custom questions for this scan</label>
            <span className={styles.labelHint}>
              {customQuestionCount} custom question{customQuestionCount === 1 ? "" : "s"} added
            </span>
          </div>
          <div className={styles.customQuestionPanel}>
            <p>
              Optional. These run only in this scan and will not affect your benchmark score.
            </p>
            {form.customQuestions.length > 0 && (
              <div className={styles.customQuestionList}>
                {form.customQuestions.map((question, index) => (
                  <div key={index} className={styles.customQuestionRow}>
                    <textarea
                      className={styles.customQuestionInput}
                      value={question}
                      placeholder="Add a customer question you want AISO to test..."
                      onChange={(event) => updateCustomQuestion(index, event.target.value)}
                    />
                    <button
                      type="button"
                      className={styles.removeMiniBtn}
                      onClick={() => removeCustomQuestion(index)}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
            <button type="button" className={styles.secondaryBtn} onClick={addCustomQuestion}>
              Add custom question
            </button>
          </div>
        </div>
        </>
        )}
        <div className={styles.fieldGroup}>
          {usesManagedKeys ? (
            <p className={styles.byokTrust}>
              <strong>Scans run on AISO-managed keys.</strong> No API key needed — your plan includes managed provider access.
            </p>
          ) : (
            <button
              type="button"
              className={styles.byokToggle}
              onClick={() => setKeysOpen((o) => !o)}
              aria-expanded={byokPanelOpen}
              id="ob-byok-toggle"
            >
              <span className={`${styles.byokArrow} ${byokPanelOpen ? styles.byokArrowOpen : ""}`}>▶</span>
              {missingKeys.length
                ? `Add API keys for ${missingKeys.length} selected platform${missingKeys.length === 1 ? "" : "s"}`
                : `API keys ready (${selectedProviderKeysSet}/${form.providers.length} selected)`}
            </button>
          )}
          {byokPanelOpen && (
            <div className={styles.byokPanel}>
              <p className={styles.byokTrust}>
                <strong>Keys are never saved to AISO.</strong> They stay in browser session memory and are sent only with this scan request.
              </p>
              {visibleValidationError && <div className={styles.validationError} role="alert">{visibleValidationError}</div>}
              <div className={styles.byokFields}>
                {PROVIDERS.map((p) => {
                  const selected = form.providers.includes(p.id);
                  const missingRequired = selected && !keySet[p.id];
                  return (
                    <div key={p.id} className={`${styles.byokRow} ${missingRequired ? styles.byokRowMissing : ""}`}>
                      <span className={styles.byokProvider}>
                        <span style={{ width: 8, height: 8, borderRadius: "50%", background: p.color, display: "inline-block", marginRight: 6 }} />
                        {p.name}
                      </span>
                      {keySet[p.id]
                        ? <span className={styles.byokSaved}>Session active</span>
                        : missingRequired
                        ? <span className={styles.byokRequired}>Required</span>
                        : hadKeyPreviousSession(p.id)
                        ? <span className={styles.byokPrev}>Re-enter key</span>
                        : !selected
                        ? <span className={styles.byokOptional}>Optional</span>
                        : null}
                      <input
                        type="password"
                        className={`input ${styles.byokInput}`}
                        placeholder={keySet[p.id] ? "Key active" : `Paste your ${p.name} API key`}
                        autoComplete="off"
                        spellCheck={false}
                        aria-invalid={missingRequired}
                        aria-label={`${p.name} API key`}
                        onChange={(e) => handleKeyInput(p.id, e.target.value)}
                      />
                      <a
                        href={p.id === "openai" ? "https://platform.openai.com/api-keys"
                          : p.id === "claude" ? "https://console.anthropic.com/settings/keys"
                          : p.id === "perplexity" ? "https://www.perplexity.ai/settings/api"
                          : "https://aistudio.google.com/app/apikey"}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.byokGetKey}
                      >
                        Get key
                      </a>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
        <div className={styles.scanSummary}>
          {[
            { k: "Business", v: form.businessName },
            { k: "Website", v: form.websiteUrl },
            { k: "Objective", v: objectiveSummary(profile.scan_objective) },
            { k: "Competitors", v: hasCompetitors ? `${competitorCount} added` : "Not added" },
            { k: "Platforms", v: providerNames },
            { k: "Groups", v: form.groups.join(", ") },
          ].map(({ k, v }) => (
            <div key={k} className={styles.summaryRow}>
              <span className={styles.summaryKey}>{k}</span>
              <span className={styles.summaryVal}>{v}</span>
            </div>
          ))}
        </div>
      </div>
      <div className={styles.navRow}>
        <button type="button" className={styles.backBtn} onClick={onBack}>Back</button>
        <button type="button" className={styles.nextBtn} onClick={handleLaunchClick} id="ob-launch-btn">
          Launch scan
        </button>
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  const router = useRouter();
  const { entitlements } = useEntitlements();
  // Free tier brings its own keys; pro/custom run on managed server keys.
  const usesManagedKeys = entitlements?.uses_managed_keys ?? false;
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormState>(DEFAULT);
  const [clientId, setClientId] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [context, setContext] = useState<ClientContextData | null>(null);
  const [profile, setProfile] = useState<ContextProfile>(emptyProfile(DEFAULT));
  const [, setDraftFlags] = useState<Record<string, string>>({});
  const [verticalOptions, setVerticalOptions] = useState<VerticalOption[]>([]);
  const [verticalOptionsStatus, setVerticalOptionsStatus] = useState<ActionStatus>("loading");
  const [verticalOptionsError, setVerticalOptionsError] = useState<string | null>(null);
  const [intakeSchema, setIntakeSchema] = useState<IntakeSchema | null>(null);
  const [schemaStatus, setSchemaStatus] = useState<ActionStatus>("idle");
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [, setWarnings] = useState<string[]>([]);
  const [basicsStatus, setBasicsStatus] = useState<ActionStatus>("idle");
  const [discovering, setDiscovering] = useState(false);
  const [savingContext, setSavingContext] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanIdx, setScanIdx] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [prompts, setPrompts] = useState<ReviewPrompt[]>([]);
  const [promptsStatus, setPromptsStatus] = useState<ActionStatus>("idle");
  const [promptsError, setPromptsError] = useState<string | null>(null);
  const [promptsModel, setPromptsModel] = useState<string>("");
  const [promptVariation, setPromptVariation] = useState(0);
  const [draftedFields, setDraftedFields] = useState<DraftedFields | null>(null);
  const [draftFieldsStatus, setDraftFieldsStatus] = useState<ActionStatus>("idle");
  const [draftFieldsModel, setDraftFieldsModel] = useState<string>("");
  const [draftVariation, setDraftVariation] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, [step]);

  useEffect(() => {
    if (!scanning) return;
    const id = setInterval(() => setScanIdx((i) => (i + 1) % SCAN_STEPS.length), 1800);
    return () => clearInterval(id);
  }, [scanning]);

  useEffect(() => {
    let active = true;
    async function loadVerticalOptions() {
      setVerticalOptionsStatus("loading");
      setVerticalOptionsError(null);
      try {
        const options = await getIntakeVerticals();
        if (!active) return;
        setVerticalOptions(options);
        setVerticalOptionsStatus("idle");
      } catch (err) {
        if (!active) return;
        setVerticalOptions([]);
        setVerticalOptionsStatus("error");
        setVerticalOptionsError(err instanceof Error ? err.message : "Unable to load business types.");
      }
    }
    void loadVerticalOptions();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    async function loadSchema() {
      if (!form.vertical.trim()) {
        setIntakeSchema(null);
        setSchemaStatus("idle");
        setSchemaError(null);
        return;
      }
      setSchemaStatus("loading");
      setSchemaError(null);
      try {
        const schema = await getIntakeSchema(form.vertical);
        if (!active) return;
        setIntakeSchema(schema);
        setSchemaStatus("idle");
      } catch (err) {
        if (!active) return;
        setIntakeSchema(null);
        setSchemaStatus("error");
        setSchemaError(err instanceof Error ? err.message : "Unable to load intake schema.");
      }
    }
    void loadSchema();
    return () => {
      active = false;
    };
  }, [form.vertical]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  useEffect(() => {
    let active = true;
    async function loadExistingClient() {
      try {
        const res = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!res.ok) return;
        const clients: ExistingClient[] = await res.json();
        const client = clients[0] ?? null;
        if (!client || !active) return;
        setClientId(client.id);
        let nextForm: FormState = {
          ...DEFAULT,
          businessName: client.name,
          websiteUrl: client.url,
          industry: client.industry ?? "",
          location: client.location ?? "",
          competitors: client.competitors?.join(", ") ?? "",
        };
        setForm(nextForm);
        const [loadedContext, savedProfile] = await Promise.all([
          getClientContext(client.id),
          getOnboardingProfile(client.id),
        ]);
        if (!active) return;
        if (savedProfile?.vertical) {
          try {
            const savedSchema = await getIntakeSchema(savedProfile.vertical);
            if (!active) return;
            nextForm = formFromExistingProfile(client, savedProfile, savedSchema);
            setIntakeSchema(savedSchema);
            setSchemaStatus("idle");
            setSchemaError(null);
          } catch (err) {
            if (!active) return;
            setSchemaError(err instanceof Error ? err.message : "Unable to load saved intake fields.");
          }
        }
        setForm(nextForm);
        if (!active || !loadedContext) return;
        setContext(loadedContext);
        if (loadedContext.profile_json) {
          setProfile(normalizedProfile(loadedContext.profile_json));
          setWarnings(loadedContext.warnings_json ?? []);
          setDraftFlags(loadedContext.evidence_json?.profile_draft?.field_sources ?? {});
        } else {
          setProfile(emptyProfile(nextForm));
        }
      } catch {
        // Prefill is a convenience only.
      }
    }
    void loadExistingClient();
    return () => {
      active = false;
    };
  }, []);

  async function runDiscovery(id: string, sourceForm: FormState = form) {
    setDiscovering(true);
    setError(null);
    try {
      const workspace = await createCrawlerWorkspace(id, sourceForm.websiteUrl);
      setWorkspaceId(workspace.workspace_id);
      let job = await createCrawlJob(workspace.workspace_id);

      setContext({
        client_id: id,
        status: "discovering",
        profile_json: null,
        evidence_json: null,
        warnings_json: ["Website discovery is running. AISO is reading public pages only."],
      });

      for (let attempt = 0; attempt < DISCOVERY_MAX_POLLS && ["queued", "running"].includes(job.status); attempt += 1) {
        await sleep(DISCOVERY_POLL_MS);
        job = await getCrawlJob(job.job_id);
      }

      if (["queued", "running"].includes(job.status)) {
        setError("Website discovery is still running. You can wait, refresh discovery, or enter the context manually.");
        return;
      }

      const discoveredContext = await getClientContext(id);
      const baseContext: ClientContextData = discoveredContext?.profile_json
        ? discoveredContext
        : { client_id: id, status: "draft", profile_json: emptyProfile(sourceForm), evidence_json: null, warnings_json: [] };
      const baseProfile = normalizedProfile(baseContext.profile_json ?? emptyProfile(sourceForm));
      setContext({ ...baseContext, profile_json: baseProfile });
      setWarnings(baseContext.warnings_json ?? []);
      setProfile(baseProfile);
      // AI drafts the confirmable business fields (description/industry/audiences/
      // competitors) from the crawled homepage text. The user confirms next.
      await loadDraftFields(id, 0);

      if (job.status === "failed" || baseContext.status === "failed") {
        setError("AISO could not finish reading your website. You can still fill in the details on the next step.");
      }
    } catch (err) {
      setContext(null);
      setWorkspaceId(null);
      setDraftFlags({});
      setWarnings(["Website discovery failed safely. Please confirm the client context manually."]);
      setProfile(emptyProfile(sourceForm));
      setError(err instanceof Error ? err.message : "Website discovery failed safely.");
    } finally {
      setDiscovering(false);
    }
  }

  async function handleBasicsNext() {
    setBasicsStatus("loading");
    setError(null);
    try {
      const validationErrors = validateIntake(form, intakeSchema);
      if (validationErrors.length > 0 || !intakeSchema) {
        setBasicsStatus("error");
        setError(`Complete required intake fields: ${validationErrors.join(", ")}`);
        return;
      }
      const nextForm = legacyFormFromIntake(form, intakeSchema);
      // Pass the loaded business id so the backend reuses it (no duplicate);
      // it returns that same id, so this never points at a new profile.
      const client = await startPipelineOnboarding(nextForm, intakeSchema, clientId);
      setForm(nextForm);
      setClientId(client.id);
      setWorkspaceId(null);
      const confirmedProfile = context?.profile_json;
      if (contextMatchesForm(context, nextForm, client.id) && confirmedProfile) {
        setProfile(normalizedProfile(confirmedProfile));
        setWarnings(context.warnings_json ?? []);
        setDraftFlags(context.evidence_json?.profile_draft?.field_sources ?? {});
        setStep(3);
        return;
      }
      setStep(2);
      await runDiscovery(client.id, nextForm);
    } catch (err) {
      setBasicsStatus("error");
      setError(err instanceof Error ? err.message : "Unable to save the business.");
      return;
    } finally {
      setBasicsStatus("idle");
    }
  }

  async function handleConfirmContext() {
    if (!clientId) return;
    const fields = draftedFields;
    if (!fields || !fields.description.trim() || !fields.industry.trim()) {
      setError("Add what you do and your industry before continuing.");
      return;
    }
    setSavingContext(true);
    setError(null);
    try {
      const item = (name: string, type: string): ContextItem => ({ name: name.trim(), type, confidence: 1 });
      const competitors = fields.competitors.map((c) => c.trim()).filter(Boolean);
      const audiences = fields.audiences.map((a) => a.trim()).filter(Boolean);
      // Build a minimal confirmed profile from the AI-drafted fields - no offerings/
      // locations. industry -> category and audiences -> personas feed the prompts.
      const confirmedProfile: ContextProfile = {
        ...emptyProfile(form),
        categories: [item(fields.industry, "category")],
        competitors: competitors.map((c) => item(c, "competitor_business")),
        personas: audiences.map((a) => item(a, "persona")),
        differentiators: fields.description.trim() ? [item(fields.description, "differentiator")] : [],
      };
      if (workspaceId && context?.status !== "confirmed") {
        try {
          await editCrawlerBusinessProfile(workspaceId, confirmedProfile);
          await approveCrawlerBusinessProfile(workspaceId);
        } catch (err) {
          if (!isApprovedCrawlerProfileConflict(err)) throw err;
        }
        setWorkspaceId(null);
      }
      await confirmPipelineBusinessProfile(clientId, confirmedProfile);
      const saved = await saveClientContext(clientId, confirmedProfile, []);
      setContext(saved);
      if (saved.status === "confirmed") setWorkspaceId(null);
      setProfile(normalizedProfile(saved.profile_json ?? confirmedProfile));
      setForm({ ...form, competitors: competitors.join(", ") });
      setStep(4);
      void loadPrompts(clientId, 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save your business.");
    } finally {
      setSavingContext(false);
    }
  }

  async function loadPrompts(cid: string, variation: number) {
    setPromptsStatus("loading");
    setPromptsError(null);
    try {
      const { branded, category, model } = await generatePrompts(cid, variation);
      setPrompts([...branded, ...category]);
      setPromptsModel(model);
      setPromptsStatus("idle");
    } catch (err) {
      setPromptsStatus("error");
      setPromptsError(err instanceof Error ? err.message : "Unable to generate prompts.");
    }
  }

  function handleRegeneratePrompts() {
    if (!clientId) return;
    const next = promptVariation + 1;
    setPromptVariation(next);
    void loadPrompts(clientId, next);
  }

  function updatePrompt(index: number, text: string) {
    setPrompts((prev) => prev.map((p, i) => (i === index ? { ...p, text } : p)));
  }

  function removePrompt(index: number) {
    setPrompts((prev) => prev.filter((_, i) => i !== index));
  }

  function addPrompt(kind: PromptKind) {
    setPrompts((prev) => [
      ...prev,
      {
        text: "",
        kind,
        journey_stage: "J2",
        brand_frame: kind === "branded" ? "brand_only" : "unbranded_category",
      },
    ]);
  }

  async function loadDraftFields(cid: string, variation: number) {
    setDraftFieldsStatus("loading");
    setError(null);
    try {
      const fields = await draftFields(cid, variation);
      setDraftedFields({
        description: fields.description,
        industry: fields.industry,
        audiences: fields.audiences,
        competitors: fields.competitors,
      });
      setDraftFieldsModel(fields.model);
      setDraftFieldsStatus("idle");
    } catch {
      // Cold-start / thin site: don't dead-end - drop to an empty, fillable form.
      setDraftedFields(emptyDraftedFields());
      setDraftFieldsStatus("error");
    }
  }

  function handleRegenerateDraft() {
    if (!clientId) return;
    const next = draftVariation + 1;
    setDraftVariation(next);
    void loadDraftFields(clientId, next);
  }

  function setDraftText(key: "description" | "industry", value: string) {
    setDraftedFields((prev) => ({ ...(prev ?? emptyDraftedFields()), [key]: value }));
  }

  function setDraftList(key: "audiences" | "competitors", values: string[]) {
    setDraftedFields((prev) => ({ ...(prev ?? emptyDraftedFields()), [key]: values }));
  }

  function handleManualContext() {
    setWorkspaceId(null);
    setDraftFlags({});
    setProfile(emptyProfile(form));
    setWarnings(["Classification confidence is low. Please confirm services, competitors, and locations manually."]);
    setStep(3);
  }

  async function handleLaunch(customQuestions: string[] = []) {
    setError(null);
    if (!usesManagedKeys) {
      const missingKeys = missingSelectedProviderKeys(form.providers);
      if (missingKeys.length > 0) {
        const message = `Add API keys for selected providers: ${missingKeys.map(providerName).join(", ")}.`;
        setKeyError(message);
        setError(message);
        return;
      }
    }
    if (!clientId) {
      setError("Business profile is missing. Go back and save business basics.");
      return;
    }
    if (context?.status !== "confirmed") {
      setStep(3);
      setError("Confirm the client context before launching the scan.");
      return;
    }
    const approvedPrompts = prompts
      .map((p) => ({ ...p, text: p.text.replace(/\s+/g, " ").trim() }))
      .filter((p) => p.text.length > 0);
    if (approvedPrompts.length === 0 && customQuestions.length === 0) {
      setStep(4);
      setError("Add or generate at least one prompt before launching.");
      return;
    }
    setKeyError(null);
    setScanning(true);

    try {
      const byokKeys = usesManagedKeys ? {} : getAllKeys();
      const scanId = await createScan(clientId, form.providers, form.groups, customQuestions, approvedPrompts, byokKeys);
      setForm((prev) => ({ ...prev, customQuestions: [] }));
      pollRef.current = setInterval(async () => {
        try {
          const result = await pollScan(clientId, scanId);
          if (result.status === "complete" || result.status === "failed") {
            clearInterval(pollRef.current!);
            if (result.skipped_providers?.length) setSkipped(result.skipped_providers);
            if (result.status === "failed") {
              setScanning(false);
              setError(result.error || "The scan failed. Check your API keys and try again.");
              return;
            }
            setTimeout(() => router.push(`/dashboard/scans/${scanId}`), 1500);
          }
        } catch {
          // Poll errors are transient.
        }
      }, 4000);
    } catch (err) {
      setScanning(false);
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    }
  }

  const progress = ((step - 1) / (STEPS.length - 1)) * 100;
  const cardClass = `${styles.card} ${step === 3 ? styles.contextCard : ""}`;

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <div className={styles.topLogo}>
          <span className={styles.logoMark}>◆</span>
          <span className="gradient-text">AISO</span>
        </div>
        <div className={styles.topActions}>
          <span className={styles.stepCounter}>Step {step} of {STEPS.length}</span>
          <Link href="/dashboard" className={styles.skipLink}>
            Skip for now
          </Link>
        </div>
      </div>

      <div className={styles.progressTrack}>
        <div className={styles.progressFill} style={{ width: `${progress}%` }} />
      </div>

      <div className={styles.stepPills}>
        {STEPS.map((s, i) => (
          <div key={s.num} style={{ display: "flex", alignItems: "center" }}>
            <div className={`${styles.stepPill} ${step === s.num ? styles.active : step > s.num ? styles.done : ""}`}>
              <span className={styles.stepNum}>{step > s.num ? "✓" : s.num}</span>
              {s.label}
            </div>
            {i < STEPS.length - 1 && <div className={styles.stepConnector} />}
          </div>
        ))}
      </div>

      <div className={cardClass}>
        {step === 1 && (
          <Step1
            form={form}
            set={(nextForm) => {
              setForm(nextForm);
              setProfile(emptyProfile(nextForm));
            }}
            verticalOptions={verticalOptions}
            schema={intakeSchema}
            verticalOptionsStatus={verticalOptionsStatus}
            verticalOptionsError={verticalOptionsError}
            schemaStatus={schemaStatus}
            schemaError={schemaError}
            onNext={() => void handleBasicsNext()}
            status={basicsStatus}
            error={step === 1 ? error : null}
          />
        )}
        {step === 2 && (
          <Step2
            context={context}
            discovering={discovering}
            error={error}
            onBack={() => setStep(1)}
            onRetry={() => { if (clientId) void runDiscovery(clientId); }}
            onManual={handleManualContext}
            onNext={() => setStep(3)}
          />
        )}
        {step === 3 && (
          <StepConfirm
            fields={draftedFields ?? emptyDraftedFields()}
            status={draftFieldsStatus}
            model={draftFieldsModel}
            onChangeText={setDraftText}
            onChangeList={setDraftList}
            onRegenerate={handleRegenerateDraft}
            onBack={() => setStep(context ? 2 : 1)}
            onConfirm={() => void handleConfirmContext()}
            saving={savingContext}
            error={step === 3 ? error : null}
          />
        )}
        {step === 4 && (
          <StepPrompts
            prompts={prompts}
            status={promptsStatus}
            error={promptsError}
            model={promptsModel}
            onUpdate={updatePrompt}
            onRemove={removePrompt}
            onAdd={addPrompt}
            onRegenerate={handleRegeneratePrompts}
            onBack={() => setStep(3)}
            onNext={() => setStep(5)}
          />
        )}
        {step === 5 && (
          <Step4
            form={form}
            profile={profile}
            set={setForm}
            promptCount={prompts.filter((p) => p.text.trim().length > 0).length}
            onBack={() => setStep(4)}
            onLaunch={(customQuestions) => void handleLaunch(customQuestions)}
            scanning={scanning}
            scanIdx={scanIdx}
            error={error}
            skipped={skipped}
            externalError={keyError}
            usesManagedKeys={usesManagedKeys}
            onClearExternalError={() => {
              setKeyError(null);
              setError(null);
            }}
          />
        )}
      </div>
    </div>
  );
}
