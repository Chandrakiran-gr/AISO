"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import styles from "./onboarding.module.css";
import { setKey, getKey, getAllKeys, hadKeyPreviousSession, clearKey, type Provider } from "@/lib/byok";
import { INTENT_GROUPS } from "@/lib/intent-groups";

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

interface FormState {
  businessName: string;
  websiteUrl: string;
  industry: string;
  location: string;
  competitors: string;
  providers: string[];
  groups: string[];
}

const DEFAULT: FormState = {
  businessName: "",
  websiteUrl: "",
  industry: "",
  location: "",
  competitors: "",
  providers: ["openai", "claude", "perplexity", "gemini"],
  groups: GROUPS.map((group) => group.id),
};

type ExistingClient = {
  id: string;
  name: string;
  url: string;
  industry: string | null;
  location: string | null;
  competitors: string[] | null;
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
  objective: string;
  label: string;
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
  evidence_json: { page_count?: number; pages?: unknown[]; warnings?: string[] } | null;
  warnings_json: string[];
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
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 10);
}

function competitorNamesFromProfile(profile: ContextProfile): string[] {
  return profile.competitors.map((item) => item.name.trim()).filter(Boolean);
}

function defaultScanObjective(): ScanObjective {
  return {
    objective: SCAN_OBJECTIVES[0].id,
    label: SCAN_OBJECTIVES[0].label,
    custom: "",
    source_url: "manual_onboarding",
    confidence: 0.9,
  };
}

function objectiveLabel(id: string): string {
  return SCAN_OBJECTIVES.find((objective) => objective.id === id)?.label ?? SCAN_OBJECTIVES[0].label;
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
  const scanObjective = profile.scan_objective ?? defaultScanObjective();
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
    scan_objective: {
      ...scanObjective,
      label: objectiveLabel(scanObjective.objective),
      custom: scanObjective.custom ?? "",
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
    goals: [manualItem(`Choose the right ${form.industry.trim() || "provider"}`, "goal")],
    personas: [manualItem("Local customers", "persona")],
    scan_objective: defaultScanObjective(),
    buyer_contexts: [],
    differentiators: [],
    guardrails: [
      "Do not compare product brands as competitors.",
      "Do not treat offering groups as bookable services unless explicitly marked bookable.",
      "Do not use visibility-only markets for urgent booking prompts.",
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
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 30)
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

function contextMatchesForm(context: ClientContextData | null, form: FormState, clientId: string): boolean {
  if (context?.status !== "confirmed" || context.client_id !== clientId || !context.profile_json) {
    return false;
  }
  const contextUrl = context.profile_json.business?.website_url ?? "";
  return contextUrl.trim().toLowerCase() === form.websiteUrl.trim().toLowerCase();
}

async function createClient(slug: string, form: FormState): Promise<ExistingClient> {
  const res = await fetch(`${API}/v1/clients`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: slug,
      display_name: form.businessName,
      url: form.websiteUrl,
      industry: form.industry || null,
      location: form.location || null,
      competitors: parseCompetitors(form.competitors),
    }),
  });
  if (!res.ok) throw new Error(`Failed to save business (${res.status})`);
  return res.json();
}

async function getClientContext(clientId: string): Promise<ClientContextData | null> {
  const res = await fetch(`${API}/v1/clients/${clientId}/context`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

async function discoverClientContext(clientId: string): Promise<ClientContextData> {
  const res = await fetch(`${API}/v1/clients/${clientId}/context/discover`, { method: "POST" });
  if (!res.ok) throw new Error(`Website discovery failed (${res.status})`);
  return res.json();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
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
  if (!res.ok) throw new Error(`Failed to confirm client context (${res.status})`);
  return res.json();
}

async function createScan(
  clientId: string,
  providers: string[],
  groups: string[],
  byokKeys: Record<string, string>,
): Promise<string> {
  const res = await fetch(`${API}/v1/clients/${clientId}/scans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: clientId,
      providers,
      groups,
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
  onNext,
  status,
  error,
}: {
  form: FormState;
  set: (f: FormState) => void;
  onNext: () => void;
  status: ActionStatus;
  error: string | null;
}) {
  const valid = form.businessName.trim().length > 0 && form.websiteUrl.startsWith("http");
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (valid && status !== "loading") onNext(); }}>
      <span className={styles.stepBadge}>Step 1 of 4 · Business basics</span>
      <h2 className={styles.stepTitle}>Tell AISO which business to analyze</h2>
      <p className={styles.stepSubtitle}>
        The website is the source of truth. These details help AISO understand the business faster if the site is vague.
      </p>
      {error && <div className={styles.validationError} role="alert">{error}</div>}
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
              <label className={styles.label} htmlFor="ob-industry">Business category</label>
              <span className={styles.labelHint}>Optional</span>
            </div>
            <input
              id="ob-industry"
              className="input"
              type="text"
              placeholder="Facial spa, B2B SaaS, roofing company"
              value={form.industry}
              onChange={(e) => set({ ...form, industry: e.target.value })}
            />
            <p className={styles.fieldHelp}>Used to avoid generic questions if the website does not clearly explain the category.</p>
          </div>
          <div className={styles.fieldGroup}>
            <div className={styles.labelRow}>
              <label className={styles.label} htmlFor="ob-location">Primary market</label>
              <span className={styles.labelHint}>Optional</span>
            </div>
            <input
              id="ob-location"
              className="input"
              type="text"
              placeholder="Newton, Greater Boston, United States"
              value={form.location}
              onChange={(e) => set({ ...form, location: e.target.value })}
            />
            <p className={styles.fieldHelp}>Used for location-aware questions when the website has broad or unclear service areas.</p>
          </div>
        </div>
        <div className={styles.fieldGroup}>
          <div className={styles.labelRow}>
            <label className={styles.label} htmlFor="ob-competitors">Competitors to compare against</label>
            <span className={styles.labelHint}>Recommended</span>
          </div>
          <input
            id="ob-competitors"
            className="input"
            type="text"
            placeholder="Competitor A, Competitor B, Competitor C"
            value={form.competitors}
            onChange={(e) => set({ ...form, competitors: e.target.value })}
          />
          <p className={styles.fieldHelp}>Add competitors only if you know them. AISO will skip competitor-only coverage when this is blank.</p>
        </div>
      </div>
      <div className={styles.navRow}>
        <div />
        <button type="submit" className={styles.nextBtn} disabled={!valid || status === "loading"} id="ob-step1-next">
          {status === "loading" ? "Saving..." : "Read website and build profile"}
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
  const readyToReview = !isRunning && status !== "failed";
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
          <strong>{isRunning ? "Discovering services, locations, proof, and CTAs" : "Discovery finished"}</strong>
          <p>
            {isRunning
              ? "This usually takes a few seconds for small business sites."
              : `${pageCount} public page${pageCount === 1 ? "" : "s"} reviewed. Continue to review and edit the extracted client context.`}
          </p>
        </div>
      </div>

      {readyToReview && (
        <div className={styles.reviewHint}>
          <strong>Extracted context is ready</strong>
          <span>The next step shows the discovered offerings, competitors, locations, personas, and proof signals before any scan runs.</span>
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
          <button type="button" className={styles.nextBtn} onClick={onNext} disabled={isRunning || status === "failed"}>
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
}: {
  title: string;
  hint: string;
  items: ContextItem[];
  type: string;
  onChange: (items: ContextItem[]) => void;
  extra?: Partial<ContextItem>;
}) {
  return (
    <section className={styles.contextSection}>
      <div className={styles.contextSectionHeader}>
        <div>
          <h3>{title}</h3>
          <p>{hint}</p>
        </div>
        <span>{items.length}</span>
      </div>
      <textarea
        className={styles.contextTextarea}
        value={itemLines(items)}
        onChange={(event) => onChange(linesToItems(event.target.value, type, extra))}
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
}: {
  contexts: BuyerContext[];
  onChange: (contexts: BuyerContext[]) => void;
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
        <span>{safeContexts.length}</span>
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
                  placeholder="Customer type, e.g. Sensitive skin"
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
  onBack,
  onConfirm,
  saving,
  error,
}: {
  profile: ContextProfile;
  setProfile: (profile: ContextProfile) => void;
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
  function updateScanObjective(objective: string, custom?: string) {
    setProfile({
      ...profile,
      scan_objective: {
        objective,
        label: objectiveLabel(objective),
        custom: custom ?? profile.scan_objective?.custom ?? "",
        source_url: "manual_onboarding",
        confidence: 0.9,
      },
    });
  }
  const scanObjective = profile.scan_objective ?? defaultScanObjective();
  const buyerContexts = profile.buyer_contexts ?? [];
  return (
    <div>
      <span className={styles.stepBadge}>Step 3 of 4 · Review business profile</span>
      <h2 className={styles.stepTitle}>Review what AISO learned before scanning</h2>
      <p className={styles.stepSubtitle}>
        AISO uses this profile to create the question bank. Fix anything that looks wrong before launching.
      </p>
      <div className={styles.reviewGuide}>
        <div>
          <strong>1. Check the profile</strong>
          <span>Each box is editable. Keep one item per line and remove anything that is not real.</span>
        </div>
        <div>
          <strong>2. Separate meanings</strong>
          <span>Services, service groups, product brands, competitors, and locations are used differently.</span>
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
          <span>1</span>
        </div>
        <select
          className="input"
          value={scanObjective.objective}
          onChange={(event) => updateScanObjective(event.target.value)}
        >
          {SCAN_OBJECTIVES.map((objective) => (
            <option key={objective.id} value={objective.id}>{objective.label}</option>
          ))}
        </select>
        <textarea
          className={styles.contextTextarea}
          value={scanObjective.custom ?? ""}
          onChange={(event) => updateScanObjective(scanObjective.objective, event.target.value)}
          placeholder="Optional custom objective"
          rows={2}
        />
      </section>
      <div className={styles.contextGrid}>
        <BuyerContextSection
          contexts={buyerContexts}
          onChange={(items) => setProfile({ ...profile, buyer_contexts: items })}
        />
        <ContextSection
          title="Categories"
          hint="Broad business categories, not individual services."
          items={profile.categories}
          type="category"
          onChange={(items) => update("categories", items)}
        />
        <ContextSection
          title="Offering groups"
          hint="Groups like Signature Facials. Not bookable unless explicitly listed."
          items={profile.offering_groups}
          type="offering_group"
          extra={{ bookable: false }}
          onChange={(items) => update("offering_groups", items)}
        />
        <ContextSection
          title="Bookable or buyable offerings"
          hint="Concrete services/products customers can book, buy, or request."
          items={profile.offerings}
          type="offering"
          extra={{ bookable: true }}
          onChange={(items) => update("offerings", items)}
        />
        <ContextSection
          title="Product brands"
          hint="Brands used, sold, or carried. Not competitors."
          items={profile.product_brands}
          type="product_brand"
          onChange={(items) => update("product_brands", items)}
        />
        <ContextSection
          title="Competitors"
          hint="Recommended for competitor and head-to-head insights. Leave blank to skip competitor-only coverage."
          items={profile.competitors}
          type="competitor_business"
          onChange={(items) => update("competitors", items)}
        />
        <ContextSection
          title="Physical locations"
          hint="Places tied to in-person availability."
          items={profile.locations.physical_locations}
          type="physical_location"
          onChange={(items) => updateLocations("physical_locations", items)}
        />
        <ContextSection
          title="Service areas"
          hint="Areas where the business can serve or take customers."
          items={profile.locations.service_areas}
          type="service_area"
          onChange={(items) => updateLocations("service_areas", items)}
        />
        <ContextSection
          title="Visibility markets"
          hint="Broader markets for awareness questions, not urgent booking prompts."
          items={profile.locations.visibility_markets}
          type="visibility_market"
          extra={{ usage: "visibility_only" }}
          onChange={(items) => updateLocations("visibility_markets", items)}
        />
        <ContextSection
          title="Goals"
          hint="Customer outcomes AISO should test."
          items={profile.goals}
          type="goal"
          onChange={(items) => update("goals", items)}
        />
        <ContextSection
          title="Personas"
          hint="Customer types, occasions, constraints, or use cases. These become customer-intent prompts."
          items={profile.personas}
          type="persona"
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
  onLaunch: () => void;
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
    setValidationError(null);
    onLaunch();
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
            { k: "Objective", v: profile.scan_objective?.label ?? objectiveLabel("high_intent_visibility") },
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
  const [context, setContext] = useState<ClientContextData | null>(null);
  const [profile, setProfile] = useState<ContextProfile>(emptyProfile(DEFAULT));
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
        const nextForm = {
          ...DEFAULT,
          businessName: client.name,
          websiteUrl: client.url,
          industry: client.industry ?? "",
          location: client.location ?? "",
          competitors: client.competitors?.join(", ") ?? "",
        };
        setForm(nextForm);
        const loadedContext = await getClientContext(client.id);
        if (!active || !loadedContext) return;
        setContext(loadedContext);
        if (loadedContext.profile_json) {
          setProfile(normalizedProfile(loadedContext.profile_json));
          setWarnings(loadedContext.warnings_json ?? []);
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

  async function runDiscovery(id: string) {
    setDiscovering(true);
    setError(null);
    try {
      let discovered = await discoverClientContext(id);
      setContext(discovered);
      setWarnings(discovered.warnings_json ?? []);
      setProfile(normalizedProfile(discovered.profile_json ?? emptyProfile(form)));

      for (let attempt = 0; attempt < DISCOVERY_MAX_POLLS && discovered.status === "discovering"; attempt += 1) {
        await sleep(DISCOVERY_POLL_MS);
        const latest = await getClientContext(id);
        if (!latest) continue;
        discovered = latest;
        setContext(latest);
        setWarnings(latest.warnings_json ?? []);
        setProfile(normalizedProfile(latest.profile_json ?? emptyProfile(form)));
      }

      if (discovered.status === "discovering") {
        setError("Website discovery is still running. You can wait, refresh discovery, or enter the context manually.");
      } else if (discovered.status === "failed") {
        setError("AISO could not finish website discovery. Please confirm the client context manually.");
      }
    } catch (err) {
      setContext(null);
      setWarnings(["Website discovery failed safely. Please confirm the client context manually."]);
      setProfile(emptyProfile(form));
      setError(err instanceof Error ? err.message : "Website discovery failed safely.");
    } finally {
      setDiscovering(false);
    }
  }

  async function handleBasicsNext() {
    setBasicsStatus("loading");
    setError(null);
    try {
      const client = await createClient(slugify(form.businessName), form);
      setClientId(client.id);
      const confirmedProfile = context?.profile_json;
      if (contextMatchesForm(context, form, client.id) && confirmedProfile) {
        setProfile(normalizedProfile(confirmedProfile));
        setWarnings(context.warnings_json ?? []);
        setStep(3);
        return;
      }
      setStep(2);
      await runDiscovery(client.id);
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
      setError("Add at least one bookable or buyable offering before launching a scan.");
      return;
    }
    const readyBuyerContexts = (profile.buyer_contexts ?? []).filter(buyerContextIsUsable);
    if (!profile.scan_objective?.objective) {
      setError("Choose a scan objective before configuring the scan.");
      return;
    }
    setSavingContext(true);
    setError(null);
    try {
      const normalized = normalizedProfile({ ...profile, buyer_contexts: readyBuyerContexts });
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
    setProfile(emptyProfile(form));
    setWarnings(["Classification confidence is low. Please confirm services, competitors, and locations manually."]);
    setStep(3);
  }

  async function handleLaunch() {
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
    if (!profile.scan_objective?.objective) {
      setStep(3);
      setError("Choose a scan objective before launching.");
      return;
    }
    setKeyError(null);
    setScanning(true);

    try {
      const byokKeys = getAllKeys();
      const scanId = await createScan(clientId, form.providers, form.groups, byokKeys);
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
        <span className={styles.stepCounter}>Step {step} of {STEPS.length}</span>
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
            onNext={() => void handleBasicsNext()}
            status={basicsStatus}
            error={basicsStatus === "error" ? error : null}
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
            onLaunch={() => void handleLaunch()}
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
