"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import styles from "./onboarding.module.css";
import { setKey, getKey, getAllKeys, hadKeyPreviousSession, clearKey, type Provider } from "@/lib/byok";
import { INTENT_GROUPS } from "@/lib/intent-groups";
import OptimizationObjectiveSelector from "@/components/OptimizationObjectiveSelector";

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
  { num: 4, label: "Launch" },
];

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

const SELECT_FIELD_HINTS: Record<string, string> = {
  employee_band: "Choose the company-size band that best matches the customers you want AISO to model.",
  revenue_band: "Choose the revenue band for the customers you most want to win, not necessarily every customer you could serve.",
  acv_band: "Choose the approximate yearly value of a typical customer relationship.",
  engagement_size_band: "Choose the typical project, program, retainer, or coaching engagement size.",
  price_tier_band: "Choose how customers usually perceive your product pricing.",
  price_tier: "Choose your broad customer-facing price position.",
  client_roster_size: "Choose the approximate number of active clients or accounts this profile represents.",
  aiso_use_case: "Choose whether this profile represents your own business, client work, or both.",
  deployment_model: "Choose the delivery model customers evaluate when asking AI tools about fit, risk, and adoption.",
  buying_committee_size: "Choose the number of people commonly involved in a purchase decision.",
  sales_cycle_length_band: "Choose the typical time from serious evaluation to purchase or contract signature.",
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

type PipelineProfileDraft = {
  category: string;
  icp: Record<string, unknown>;
  geographic_scope: Record<string, unknown>;
  competitors: string[];
  personas: Record<string, unknown>;
  field_flags: Record<string, string>;
  field_sources: Record<string, string>;
  rationale: Record<string, string>;
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

type ReviewBusinessProfile = {
  profile_id: string;
  company_name: string | null;
  description: string | null;
  website: string | null;
  domain: string | null;
  industry: string | null;
  products: string[];
  services: string[];
  locations: string[];
  contacts: Record<string, unknown>;
  social_links: string[];
  important_pages: unknown[];
  missing_fields: string[];
  confidence_score: number | null;
  profile_status: string;
  approved_at: string | null;
};

type ReviewBundle = {
  workspace_id: string;
  workspace_status: string;
  client_slug: string | null;
  client_name: string | null;
  profile: ReviewBusinessProfile | null;
  pages: { url: string; title?: string | null; page_type?: string | null; status: string }[];
  evidence: { field_name: string; field_value?: string | null; source_url: string; confidence?: number | null }[];
  job: CrawlJobData | null;
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

function validateIntake(form: FormState, schema: IntakeSchema | null): string[] {
  if (!form.vertical.trim()) return ["Choose your business type."];
  if (!schema) return ["Intake schema is still loading."];

  const missing: string[] = [];
  for (const field of schema.fields) {
    if (!field.required) continue;
    const raw = fieldValue(form, field.id);
    const values = field.type === "list" ? splitListValue(raw) : [raw.trim()].filter(Boolean);
    const minItems = field.validators?.min_items;
    if (minItems && values.length < minItems) {
      missing.push(`${field.label} needs at least ${minItems}`);
    } else if (!minItems && values.length === 0) {
      missing.push(field.label);
    }
  }
  return missing;
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

function selectFieldHint(field: IntakeField, value: string): string | null {
  if (field.type !== "select") return null;
  const base = SELECT_FIELD_HINTS[field.id];
  if (!value) return base ?? "Choose the closest option. AISO uses this to route question generation and scoring.";
  return base ? `${base} Selected: ${value}.` : `Selected: ${value}.`;
}

function compactHelp(...parts: Array<string | null | undefined>): string {
  return parts.map((part) => part?.trim()).filter(Boolean).join(" ");
}

function optionHelp(title: string | undefined, body: string | null | undefined, example?: string | null): string {
  return compactHelp(title ? `${title}:` : null, body, example);
}

function fieldCueText(field: IntakeField, value: string): string | null {
  const base = field.hint ?? selectFieldHint(field, value);
  const listHelp = field.type === "list" ? "Separate items with commas or line breaks." : null;
  return compactHelp(base, listHelp) || null;
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

function blankBuyerContext(): BuyerContext {
  return {
    label: "",
    audience_type: "Target customer",
    problem: "",
    desired_outcome: "",
    trigger_event: "",
    constraints: "",
    decision_criteria: "",
    priority: "medium",
    source_url: "manual_onboarding",
    confidence: 0.9,
  };
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

function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
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

function itemLines(items: ContextItem[]): string {
  return items.map((item) => item.name).join("\n");
}

function contextRows(items: ContextItem[]): number {
  const lineCount = Math.max(1, items.length);
  const wrappedRows = items.reduce((total, item) => total + Math.ceil(Math.max(item.name.length, 1) / 84), 0);
  return Math.max(3, Math.min(10, lineCount + wrappedRows));
}

function linesToItems(raw: string, type: string, extra: Partial<ContextItem> = {}): ContextItem[] {
  return raw
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((name) => manualItem(name, type, extra));
}

function sourceLabel(source?: string): string {
  if (!source) return "No source";
  if (source === "manual_onboarding" || source === "fallback") return "Manual entry";
  try {
    const url = new URL(source);
    return url.hostname.replace(/^www\./, "");
  } catch {
    return source;
  }
}

function evidenceLabels(items: ContextItem[]): string[] {
  if (items.length === 0) return [];

  const domains = Array.from(
    new Set(
      items
        .map((item) => item.source_url)
        .filter((source): source is string => Boolean(source) && source !== "manual_onboarding" && source !== "fallback")
        .map(sourceLabel),
    ),
  ).slice(0, 2);
  const manualCount = items.filter((item) => item.source_url === "manual_onboarding" || !item.source_url).length;
  const confidenceValues = items
    .map((item) => item.confidence)
    .filter((confidence): confidence is number => typeof confidence === "number");
  const averageConfidence = confidenceValues.length
    ? Math.round((confidenceValues.reduce((total, confidence) => total + confidence, 0) / confidenceValues.length) * 100)
    : null;

  const labels: string[] = [];
  if (domains.length > 0) labels.push(`Website evidence: ${domains.join(", ")}`);
  if (manualCount > 0) labels.push(`${manualCount} manual entr${manualCount === 1 ? "y" : "ies"}`);
  if (averageConfidence !== null) labels.push(`Avg confidence: ${averageConfidence}%`);
  return labels;
}

function flagLabel(flag?: string): string {
  if (flag === "crawled") return "Crawled";
  if (flag === "guessed") return "Guessed";
  if (flag === "needs_you") return "Needs you";
  return "";
}

function flagClass(flag?: string): string {
  if (flag === "crawled") return styles.flagCrawled;
  if (flag === "guessed") return styles.flagGuessed;
  if (flag === "needs_you") return styles.flagNeedsYou;
  return "";
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

async function startPipelineOnboarding(slug: string, form: FormState, schema: IntakeSchema): Promise<ExistingClient> {
  const res = await fetch(`${API}/v1/onboarding/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: slug,
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

async function getReviewBundle(workspaceId: string): Promise<ReviewBundle> {
  const res = await fetch(`${API}/v1/onboarding-workspaces/${workspaceId}/review`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to load review bundle (${res.status})`));
  return res.json();
}

async function draftPipelineProfile(clientId: string): Promise<PipelineProfileDraft> {
  const res = await fetch(`${API}/v1/onboarding/${clientId}/draft-profile`, { method: "POST" });
  if (!res.ok) throw new Error(await readApiError(res, `Failed to draft business profile (${res.status})`));
  return res.json();
}

function applyPipelineDraftToContext(
  base: ContextProfile,
  draft: PipelineProfileDraft,
  form: FormState,
): ContextProfile {
  const category = draft.category?.trim();
  const categories = category ? [manualItem(category, "category", { source_url: form.websiteUrl, confidence: 0.78 })] : base.categories;
  const competitors = draft.competitors?.length
    ? draft.competitors.map((name) => manualItem(name, "competitor_business", { source_url: "manual_onboarding" }))
    : base.competitors;
  const nap = draft.geographic_scope?.nap;
  const napName = formatNap(nap);
  const physicalLocations = napName
    ? [manualItem(napName, "physical_location", { source_url: form.websiteUrl, confidence: 0.78 })]
    : base.locations.physical_locations;

  return normalizedProfile({
    ...base,
    categories,
    competitors,
    locations: {
      ...base.locations,
      physical_locations: physicalLocations,
    },
  });
}

function formatNap(value: unknown): string {
  if (typeof value !== "object" || value === null) return "";
  const nap = value as { name?: unknown; telephone?: unknown; address?: Record<string, unknown> };
  const address = typeof nap.address === "object" && nap.address !== null ? nap.address : {};
  return [
    typeof nap.name === "string" ? nap.name : "",
    [
      address.streetAddress,
      address.addressLocality,
      address.addressRegion,
      address.postalCode,
    ].filter((part): part is string => typeof part === "string" && part.trim().length > 0).join(", "),
    typeof nap.telephone === "string" ? nap.telephone : "",
  ].filter(Boolean).join(" | ");
}

function reviewProfileToContext(review: ReviewBundle, clientId: string, form: FormState): ClientContextData {
  const profile = review.profile;
  const confidence = profile?.confidence_score ?? 0.72;
  const website = profile?.website || form.websiteUrl;
  const locations = (profile?.locations ?? []).map((name) => manualItem(name, "physical_location", {
    confidence,
    source_url: website,
  }));
  const converted: ContextProfile = normalizedProfile({
    ...emptyProfile(form),
    business: {
      name: profile?.company_name || form.businessName,
      type: "business",
      confidence,
      source_url: website,
      website_url: website,
    },
    categories: profile?.industry ? [manualItem(profile.industry, "category", { confidence, source_url: website })] : emptyProfile(form).categories,
    offerings: (profile?.services ?? []).map((name) => manualItem(name, "offering", {
      confidence,
      source_url: website,
      bookable: true,
    })),
    product_brands: (profile?.products ?? []).map((name) => manualItem(name, "product_brand", {
      confidence,
      source_url: website,
    })),
    competitors: parseCompetitors(form.competitors).map((name) => manualItem(name, "competitor_business")),
    locations: {
      ...emptyProfile(form).locations,
      physical_locations: locations,
    },
  });
  return {
    client_id: clientId,
    status: review.job?.status === "failed" ? "failed" : "draft",
    profile_json: converted,
    evidence_json: {
      page_count: review.pages.length || review.job?.pages_crawled || review.job?.pages_discovered || 0,
      pages: review.pages,
      warnings: [...(review.job?.warnings ?? []), ...(profile?.missing_fields ?? [])],
    },
    warnings_json: [...(review.job?.warnings ?? []), ...(profile?.missing_fields ?? [])],
  };
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

async function createScan(
  clientId: string,
  providers: string[],
  groups: string[],
  customQuestions: string[],
  byokKeys: Record<string, string>,
): Promise<string> {
  const res = await fetch(`${API}/v1/clients/${clientId}/scans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: clientId,
      providers,
      groups,
      custom_questions: customQuestions,
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
  function updateIntake(field: IntakeField, value: string) {
    const intake = { ...form.intake, [field.id]: value };
    let nextForm = { ...form, intake };
    if (field.patch_field === "category") nextForm = { ...nextForm, industry: value };
    if (field.patch_field === "competitors") nextForm = { ...nextForm, competitors: value };
    if (field.patch_field.includes("geographic") || field.id.includes("radius")) {
      nextForm = { ...nextForm, location: value };
    }
    set(nextForm);
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (valid && status !== "loading") onNext(); }}>
      <span className={styles.stepBadge}>Step 1 of 4 · Business basics</span>
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
        <section className={styles.intakePanel} aria-labelledby="ob-intake-heading">
          <div className={styles.intakeHeader}>
            <div>
              <h3 id="ob-intake-heading">{schema?.label ?? "Vertical intake"}</h3>
              <p>{schema?.description ?? "Loading the required intake fields for this vertical."}</p>
            </div>
            <span>{schemaStatus === "loading" ? "Loading" : `${schema?.fields.filter((field) => field.required).length ?? 0} required`}</span>
          </div>
          {schema && (
            <div className={styles.intakeGrid}>
              {schema.fields.map((field) => {
                const value = fieldValue(form, field.id);
                const controlId = `ob-intake-${field.id}`;
                const cueText = fieldCueText(field, value);
                return (
                  <div key={field.id} className={styles.fieldGroup}>
                    <div className={styles.labelRow}>
                      <label className={styles.label} htmlFor={controlId}>{field.label}{field.required ? " *" : ""}</label>
                      <span className={styles.labelTools}>
                        {cueText && <InfoCue id={`${controlId}-tip`} text={cueText} />}
                        {!field.required && <span className={styles.labelHint}>Optional</span>}
                      </span>
                    </div>
                    {field.type === "textarea" || field.type === "list" ? (
                      <textarea
                        id={controlId}
                        className={styles.contextTextarea}
                        rows={field.type === "list" ? 3 : 4}
                        placeholder={field.placeholder ?? ""}
                        value={value}
                        onChange={(e) => updateIntake(field, e.target.value)}
                      />
                    ) : field.type === "select" ? (
                      <select
                        id={controlId}
                        className="input"
                        value={value}
                        onChange={(e) => updateIntake(field, e.target.value)}
                      >
                        <option value="">Select...</option>
                        {field.options.map((option) => (
                          <option key={option} value={option}>{option}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        id={controlId}
                        className="input"
                        type="text"
                        placeholder={field.placeholder ?? ""}
                        value={value}
                        onChange={(e) => updateIntake(field, e.target.value)}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
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
          {status === "loading" ? "Saving..." : "Validate intake and read website"}
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
      <span className={styles.stepBadge}>Step 2 of 4 · Website discovery</span>
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

function ContextSection({
  title,
  hint,
  items,
  type,
  onChange,
  extra,
  flag,
}: {
  title: string;
  hint: string;
  items: ContextItem[];
  type: string;
  onChange: (items: ContextItem[]) => void;
  extra?: Partial<ContextItem>;
  flag?: string;
}) {
  const renderedItems = itemLines(items);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isEditingRef = useRef(false);

  useEffect(() => {
    if (!isEditingRef.current && textareaRef.current && textareaRef.current.value !== renderedItems) {
      textareaRef.current.value = renderedItems;
    }
  }, [renderedItems]);

  function handleChange(value: string) {
    onChange(linesToItems(value, type, extra));
  }

  function handleBlur(value: string) {
    isEditingRef.current = false;
    const normalizedItems = normalizeContextItems(linesToItems(value, type, extra));
    if (textareaRef.current) {
      textareaRef.current.value = itemLines(normalizedItems);
    }
    onChange(normalizedItems);
  }

  return (
    <section className={styles.contextSection}>
      <div className={styles.contextSectionHeader}>
        <div>
          <h3>{title}</h3>
          <p>{hint}</p>
        </div>
        <div className={styles.sectionMeta}>
          {flagLabel(flag) && <span className={`${styles.sourceFlag} ${flagClass(flag)}`}>{flagLabel(flag)}</span>}
          <span>{items.length}</span>
        </div>
      </div>
      <textarea
        ref={textareaRef}
        className={styles.contextTextarea}
        defaultValue={renderedItems}
        onFocus={() => {
          isEditingRef.current = true;
        }}
        onBlur={(event) => handleBlur(event.currentTarget.value)}
        onChange={(event) => handleChange(event.target.value)}
        rows={contextRows(items)}
      />
      {items.length > 0 && (
        <div className={styles.sourceChips}>
          {evidenceLabels(items).map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>
      )}
    </section>
  );
}

function BuyerContextSection({
  contexts,
  onChange,
  flag,
}: {
  contexts: BuyerContext[];
  onChange: (contexts: BuyerContext[]) => void;
  flag?: string;
}) {
  const safeContexts = contexts;
  function update(index: number, patch: Partial<BuyerContext>) {
    onChange(safeContexts.map((context, i) => (i === index ? { ...context, ...patch } : context)));
  }
  function remove(index: number) {
    onChange(safeContexts.filter((_, i) => i !== index));
  }
  return (
    <section className={`${styles.contextSection} ${styles.fullWidthSection}`}>
      <div className={styles.contextSectionHeader}>
        <div>
          <h3>Target customers <em>Optional</em></h3>
          <p>Add this only when you want AISO to test specific buyer needs, occasions, or constraints.</p>
        </div>
        <div className={styles.sectionMeta}>
          {flagLabel(flag) && <span className={`${styles.sourceFlag} ${flagClass(flag)}`}>{flagLabel(flag)}</span>}
          <span>{safeContexts.length}</span>
        </div>
      </div>
      {safeContexts.length === 0 ? (
        <div className={styles.optionalEmptyState}>
          <strong>No target customers added</strong>
          <span>AISO will still scan using the website, offerings, locations, competitors, and scan objective.</span>
        </div>
      ) : (
        <div className={styles.buyerContextList}>
          {safeContexts.map((context, index) => (
            <div key={`${context.label}-${index}`} className={styles.buyerContextCard}>
              <div className={styles.buyerContextTop}>
                <input
                  className={`input ${styles.compactInput}`}
                  value={context.label}
                  onChange={(event) => update(index, { label: event.target.value })}
                  placeholder="Customer type, e.g. operations leader"
                  aria-label="Buyer label"
                />
                <select
                  className={`input ${styles.compactSelect}`}
                  value={context.priority || "medium"}
                  onChange={(event) => update(index, { priority: event.target.value })}
                  aria-label="Buyer context priority"
                >
                  <option value="high">High priority</option>
                  <option value="medium">Medium priority</option>
                  <option value="low">Low priority</option>
                </select>
                <button type="button" className={styles.removeMiniBtn} onClick={() => remove(index)}>Remove</button>
              </div>
              <div className={styles.buyerContextGrid}>
                <label className={styles.buyerField}>
                  <span>Need or problem</span>
                  <textarea
                    className={styles.contextTextarea}
                    value={context.problem ?? ""}
                    onChange={(event) => update(index, { problem: event.target.value })}
                    placeholder="What this customer is trying to solve"
                    rows={2}
                  />
                </label>
                <label className={styles.buyerField}>
                  <span>Desired outcome</span>
                  <textarea
                    className={styles.contextTextarea}
                    value={context.desired_outcome ?? ""}
                    onChange={(event) => update(index, { desired_outcome: event.target.value })}
                    placeholder="What result they want"
                    rows={2}
                  />
                </label>
                <label className={styles.buyerField}>
                  <span>Concerns or constraints</span>
                  <textarea
                    className={styles.contextTextarea}
                    value={context.constraints ?? ""}
                    onChange={(event) => update(index, { constraints: event.target.value })}
                    placeholder="Risks, objections, budget, timing, special needs"
                    rows={2}
                  />
                </label>
                <label className={styles.buyerField}>
                  <span>Decision criteria</span>
                  <textarea
                    className={styles.contextTextarea}
                    value={context.decision_criteria ?? ""}
                    onChange={(event) => update(index, { decision_criteria: event.target.value })}
                    placeholder="What would make them choose"
                    rows={2}
                  />
                </label>
              </div>
            </div>
          ))}
        </div>
      )}
      <button
        type="button"
        className={styles.secondaryBtn}
        onClick={() => onChange([...safeContexts, blankBuyerContext()])}
      >
        Add target customer
      </button>
    </section>
  );
}

function Step3({
  profile,
  setProfile,
  draftFlags,
  onBack,
  onConfirm,
  saving,
  error,
}: {
  profile: ContextProfile;
  setProfile: (profile: ContextProfile) => void;
  draftFlags: Record<string, string>;
  onBack: () => void;
  onConfirm: () => void;
  saving: boolean;
  error: string | null;
}) {
  function update(key: keyof ContextProfile, items: ContextItem[]) {
    setProfile({ ...profile, [key]: items });
  }
  function updateLocations(key: keyof ContextProfile["locations"], items: ContextItem[]) {
    setProfile({ ...profile, locations: { ...profile.locations, [key]: items } });
  }
  function updateScanObjective(objectives: string[], custom?: string) {
    setProfile({
      ...profile,
      scan_objective: scanObjectiveFromSelection(
        objectives,
        custom ?? profile.scan_objective?.custom_objective ?? profile.scan_objective?.custom ?? "",
      ),
    });
  }
  const scanObjective = normalizedScanObjective(profile.scan_objective ?? defaultScanObjective());
  const selectedObjectives = selectedObjectiveIds(scanObjective);
  function toggleScanObjective(objectiveId: string) {
    const next = selectedObjectives.includes(objectiveId)
      ? selectedObjectives.filter((selected) => selected !== objectiveId)
      : [...selectedObjectives, objectiveId];
    updateScanObjective(next);
  }
  const buyerContexts = profile.buyer_contexts ?? [];
  return (
    <div>
      <span className={styles.stepBadge}>Step 3 of 4 · Review business profile</span>
      <h2 className={styles.stepTitle}>Review scan context before launch</h2>
      <p className={styles.stepSubtitle}>
        AISO uses this profile to create the question bank. Keep the context specific, factual, and free of anything that does not apply.
      </p>
      <div className={styles.reviewGuide}>
        <div>
          <strong>1. Check the profile</strong>
          <span>Each box is editable. Keep one item per line and remove anything that is not real.</span>
        </div>
        <div>
          <strong>2. Separate meanings</strong>
          <span>Offerings, offering groups, product lines, competitors, locations, and markets are used differently.</span>
        </div>
        <div>
          <strong>3. Continue when clean</strong>
          <span>Target customers are optional. The next step chooses providers, intent groups, API keys, and launches.</span>
        </div>
      </div>
      {error && <div className={styles.validationError} role="alert">{error}</div>}
      <section className={styles.contextSection}>
        <div className={styles.contextSectionHeader}>
          <div>
            <h3>What should this scan optimize for?</h3>
            <p>This changes which buyer questions are prioritized in the final bank.</p>
          </div>
          <div className={styles.sectionMeta}>
            {flagLabel(draftFlags.objective) && <span className={`${styles.sourceFlag} ${flagClass(draftFlags.objective)}`}>{flagLabel(draftFlags.objective)}</span>}
            <span>1</span>
          </div>
        </div>
        <OptimizationObjectiveSelector
          options={SCAN_OBJECTIVES}
          selectedObjectiveIds={selectedObjectives}
          customObjective={scanObjective.custom_objective ?? scanObjective.custom ?? ""}
          onToggleObjective={toggleScanObjective}
          onCustomObjectiveChange={(customObjective) => updateScanObjective(selectedObjectives, customObjective)}
        />
      </section>
      <div className={styles.contextGrid}>
        <BuyerContextSection
          contexts={buyerContexts}
          flag={draftFlags.icp}
          onChange={(items) => setProfile({ ...profile, buyer_contexts: items })}
        />
        <ContextSection
          title="Categories"
          hint="Broad business categories or product areas, not every individual offer."
          items={profile.categories}
          type="category"
          flag={draftFlags.category}
          onChange={(items) => update("categories", items)}
        />
        <ContextSection
          title="Offering groups"
          hint="Collections such as coaching programs, software plans, product lines, service packages, or memberships."
          items={profile.offering_groups}
          type="offering_group"
          extra={{ bookable: false }}
          onChange={(items) => update("offering_groups", items)}
        />
        <ContextSection
          title="Customer-facing offerings"
          hint="Specific services, products, programs, packages, subscriptions, or plans customers can buy, book, request, or evaluate."
          items={profile.offerings}
          type="offering"
          extra={{ bookable: true }}
          onChange={(items) => update("offerings", items)}
        />
        <ContextSection
          title="Product brands"
          hint="Brands, product lines, private labels, or vendors used, sold, or carried. Not competitors."
          items={profile.product_brands}
          type="product_brand"
          onChange={(items) => update("product_brands", items)}
        />
        <ContextSection
          title="Competitors"
          hint="Recommended for competitor and head-to-head insights. Leave blank to skip competitor-only coverage."
          items={profile.competitors}
          type="competitor_business"
          flag={draftFlags.competitors}
          onChange={(items) => update("competitors", items)}
        />
        <ContextSection
          title="Stores, offices, or physical locations"
          hint="Places tied to in-person availability, pickup, visits, service, or local proof."
          items={profile.locations.physical_locations}
          type="physical_location"
          flag={draftFlags.geographic_scope}
          onChange={(items) => updateLocations("physical_locations", items)}
        />
        <ContextSection
          title="Coverage, delivery, or service areas"
          hint="Areas where customers can buy, receive delivery, book service, or work with the business."
          items={profile.locations.service_areas}
          type="service_area"
          flag={draftFlags.geographic_scope}
          onChange={(items) => updateLocations("service_areas", items)}
        />
        <ContextSection
          title="Markets to measure visibility in"
          hint="Broader geographic or audience markets for awareness and comparison questions, not urgent purchase or availability prompts."
          items={profile.locations.visibility_markets}
          type="visibility_market"
          extra={{ usage: "visibility_only" }}
          flag={draftFlags.geographic_scope}
          onChange={(items) => updateLocations("visibility_markets", items)}
        />
        <ContextSection
          title="Goals"
          hint="Customer outcomes, buying jobs, or evaluation goals AISO should test."
          items={profile.goals}
          type="goal"
          onChange={(items) => update("goals", items)}
        />
        <ContextSection
          title="Audience segments or use cases"
          hint="Customer types, buyer roles, occasions, constraints, or use cases. These become customer-intent prompts."
          items={profile.personas}
          type="persona"
          flag={draftFlags.personas}
          onChange={(items) => update("personas", items)}
        />
        <ContextSection
          title="Differentiators"
          hint="Proof points, strengths, guarantees, and positioning."
          items={profile.differentiators}
          type="differentiator"
          onChange={(items) => update("differentiators", items)}
        />
      </div>
      <div className={styles.navRow}>
        <button type="button" className={styles.backBtn} onClick={onBack}>Back</button>
        <button type="button" className={styles.nextBtn} onClick={onConfirm} disabled={saving || profile.offerings.length === 0}>
          {saving ? "Saving profile..." : "Looks good, configure scan"}
        </button>
      </div>
    </div>
  );
}

function Step4({
  form,
  profile,
  set,
  onBack,
  onLaunch,
  scanning,
  scanIdx,
  error,
  skipped,
  externalError,
  onClearExternalError,
}: {
  form: FormState;
  profile: ContextProfile;
  set: (f: FormState) => void;
  onBack: () => void;
  onLaunch: (customQuestions: string[]) => void;
  scanning: boolean;
  scanIdx: number;
  error: string | null;
  skipped: string[];
  externalError: string | null;
  onClearExternalError: () => void;
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
  const byokPanelOpen = keysOpen || Boolean(visibleValidationError);
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
    if (form.groups.includes("G3") && !hasCompetitors) {
      setValidationError("G3 needs at least one competitor. Add competitors in Confirm context or deselect G3.");
      return;
    }
    const currentState = refreshKeyState();
    const missing = form.providers.filter((id) => !currentState[id as Provider]);
    if (missing.length > 0) {
      setKeysOpen(true);
      setValidationError(`Add API keys for selected providers: ${missing.map(providerName).join(", ")}.`);
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
      <span className={styles.stepBadge}>Step 4 of 4 · Configure and launch</span>
      <h2 className={styles.stepTitle}>Choose providers and launch</h2>
      <p className={styles.stepSubtitle}>
        BYOK keys are used only for this scan request. They are not saved to the database or written to logs.
      </p>
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
        <div className={styles.fieldGroup}>
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
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormState>(DEFAULT);
  const [clientId, setClientId] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [context, setContext] = useState<ClientContextData | null>(null);
  const [profile, setProfile] = useState<ContextProfile>(emptyProfile(DEFAULT));
  const [draftFlags, setDraftFlags] = useState<Record<string, string>>({});
  const [verticalOptions, setVerticalOptions] = useState<VerticalOption[]>([]);
  const [verticalOptionsStatus, setVerticalOptionsStatus] = useState<ActionStatus>("loading");
  const [verticalOptionsError, setVerticalOptionsError] = useState<string | null>(null);
  const [intakeSchema, setIntakeSchema] = useState<IntakeSchema | null>(null);
  const [schemaStatus, setSchemaStatus] = useState<ActionStatus>("idle");
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [basicsStatus, setBasicsStatus] = useState<ActionStatus>("idle");
  const [discovering, setDiscovering] = useState(false);
  const [savingContext, setSavingContext] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanIdx, setScanIdx] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

      const review = await getReviewBundle(workspace.workspace_id);
      const discoveredContext = await getClientContext(id);
      const nextContext = discoveredContext?.profile_json
        ? discoveredContext
        : reviewProfileToContext(review, id, sourceForm);
      let profileDraft: PipelineProfileDraft | null = null;
      try {
        profileDraft = await draftPipelineProfile(id);
      } catch {
        profileDraft = null;
      }
      const draftedProfile = profileDraft
        ? applyPipelineDraftToContext(normalizedProfile(nextContext.profile_json ?? emptyProfile(sourceForm)), profileDraft, sourceForm)
        : normalizedProfile(nextContext.profile_json ?? emptyProfile(sourceForm));
      const nextEvidence = {
        ...(nextContext.evidence_json ?? {}),
        profile_draft: profileDraft ? { field_sources: profileDraft.field_flags } : nextContext.evidence_json?.profile_draft,
      };

      setContext({ ...nextContext, profile_json: draftedProfile, evidence_json: nextEvidence });
      setWarnings(nextContext.warnings_json ?? []);
      setProfile(draftedProfile);
      setDraftFlags(profileDraft?.field_flags ?? nextContext.evidence_json?.profile_draft?.field_sources ?? {});

      if (job.status === "failed" || nextContext.status === "failed") {
        setError("AISO could not finish website discovery. Please confirm the client context manually.");
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
      const client = await startPipelineOnboarding(slugify(nextForm.businessName), nextForm, intakeSchema);
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
    if (profile.offerings.length === 0) {
      setError("Add at least one customer-facing offering before launching a scan.");
      return;
    }
    const readyBuyerContexts = (profile.buyer_contexts ?? []).filter(buyerContextIsUsable);
    setSavingContext(true);
    setError(null);
    try {
      const normalized = normalizedProfile({ ...profile, buyer_contexts: readyBuyerContexts });
      if (workspaceId) {
        await editCrawlerBusinessProfile(workspaceId, normalized);
        await approveCrawlerBusinessProfile(workspaceId);
      }
      await confirmPipelineBusinessProfile(clientId, normalized);
      const saved = await saveClientContext(clientId, normalized, warnings);
      setContext(saved);
      setProfile(normalizedProfile(saved.profile_json ?? normalized));
      setWarnings(saved.warnings_json ?? warnings);
      setForm({ ...form, competitors: competitorNamesFromProfile(normalized).join(", ") });
      setStep(4);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to confirm context.");
    } finally {
      setSavingContext(false);
    }
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
    const missingKeys = missingSelectedProviderKeys(form.providers);
    if (missingKeys.length > 0) {
      const message = `Add API keys for selected providers: ${missingKeys.map(providerName).join(", ")}.`;
      setKeyError(message);
      setError(message);
      return;
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
    setKeyError(null);
    setScanning(true);

    try {
      const byokKeys = getAllKeys();
      const scanId = await createScan(clientId, form.providers, form.groups, customQuestions, byokKeys);
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
            setTimeout(() => router.push("/dashboard"), 1500);
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
          <Step3
            profile={profile}
            setProfile={setProfile}
            draftFlags={draftFlags}
            onBack={() => setStep(context ? 2 : 1)}
            onConfirm={() => void handleConfirmContext()}
            saving={savingContext}
            error={step === 3 ? error : null}
          />
        )}
        {step === 4 && (
          <Step4
            form={form}
            profile={profile}
            set={setForm}
            onBack={() => setStep(3)}
            onLaunch={(customQuestions) => void handleLaunch(customQuestions)}
            scanning={scanning}
            scanIdx={scanIdx}
            error={error}
            skipped={skipped}
            externalError={keyError}
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
