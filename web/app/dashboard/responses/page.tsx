"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { PRO_UPGRADE_HREF } from "@/lib/plan";
import { canAccessRawArtifacts } from "@/lib/entitlements";
import { useEntitlements } from "@/lib/useEntitlements";
import styles from "../dashboard.module.css";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type ScanData = {
  id: string;
  status: string;
  created_at: string;
  artifacts?: ArtifactData[];
};

type ArtifactData = {
  id: string;
  artifact_type: string;
  file_format?: string | null;
  storage_path: string;
  original_filename: string | null;
  size_bytes?: number | null;
};

type CitationData = {
  id: string;
  provider: string;
  group: string | null;
  question: string | null;
  answer_excerpt: string | null;
  citation_url: string;
  citation_title: string | null;
  source_domain: string | null;
  canonical_url?: string | null;
  citation_origin?: string | null;
  web_search_used?: boolean | null;
  source_type?: string | null;
  owner_type?: string | null;
  action_role?: string | null;
  actionability_score?: number | null;
  influence_score?: number | null;
  confidence_score?: number | null;
  classification_reason?: string | null;
};

type GapSource = {
  domain: string;
  missed_query_count: number;
  providers: string[];
  groups: string[];
  example_questions: string[];
  top_urls: string[];
  owner_type?: string;
  source_type?: string;
  action_role?: string;
  actionability_score?: number;
  confidence_score?: number;
  classification_reason?: string | null;
};

type GapFix = {
  title: string;
  impact: string;
  score: number;
  why: string;
  next_step: string;
};

type GapQuery = {
  question: string;
  group: string;
  group_label: string;
  provider: string;
  appeared: boolean;
  mention_rank: number | null;
  competitors_mentioned: string[];
  cited_sources: { domain?: string | null; url?: string | null; title?: string | null }[];
  priority_score: number;
};

type GapReport = {
  summary: {
    total_provider_question_results: number;
    appeared_count: number;
    missed_count: number;
    appearance_rate: number;
    source_opportunity_count: number;
    competitor_gap_count: number;
    actionable_source_count?: number;
    competitive_evidence_count?: number;
    content_gap_count?: number;
    low_confidence_source_count?: number;
    web_search_coverage?: {
      known_source_count: number;
      used_source_count: number;
      coverage_rate: number;
    };
  };
  priority_fixes: GapFix[];
  source_opportunities: GapSource[];
  source_intelligence?: {
    direct_targets: GapSource[];
    listing_targets: GapSource[];
    publisher_targets: GapSource[];
    authority_content_gaps: GapSource[];
    competitive_evidence: GapSource[];
    noise_sources: GapSource[];
  };
  competitive_evidence?: GapSource[];
  authority_content_gaps?: GapSource[];
  noise_sources?: GapSource[];
  query_results: GapQuery[];
};

type SourceProfile = {
  id: string;
  canonical_url: string;
  source_domain: string | null;
  source_title: string | null;
  owner_type: string | null;
  source_type: string | null;
  action_role: string | null;
  actionability_score: number | null;
  influence_score: number | null;
  relevance_score: number | null;
  client_mentioned: boolean | null;
  competitors_mentioned: string[];
  topics: string[];
  fetch_status: string | null;
  classification_reason: string | null;
  citation_count: number;
  prompt_count: number;
  provider_count: number;
  example_questions: string[];
  top_urls: string[];
};

type ProofTab = "overview" | "fixes" | "missed" | "sources" | "raw";
type SourceTab = "listings" | "content" | "competitive" | "monitor";

const PROOF_TABS: { id: ProofTab; label: string; description: string }[] = [
  { id: "overview", label: "Overview", description: "Executive readout" },
  { id: "fixes", label: "Fixes", description: "What to improve" },
  { id: "missed", label: "Missed Questions", description: "Queries AI missed" },
  { id: "sources", label: "Sources", description: "Citation targets" },
  { id: "raw", label: "Raw Evidence", description: "Audit trail" },
];

const SOURCE_TABS: { id: SourceTab; label: string }[] = [
  { id: "listings", label: "Listings" },
  { id: "content", label: "Content gaps" },
  { id: "competitive", label: "Competitive evidence" },
  { id: "monitor", label: "Monitor / ignore" },
];

function initialProofTab(): ProofTab {
  if (typeof window === "undefined") return "overview";
  const tab = new URLSearchParams(window.location.search).get("tab");
  return PROOF_TABS.some((item) => item.id === tab) ? (tab as ProofTab) : "overview";
}

function initialProviderFilter(): string {
  if (typeof window === "undefined") return "all";
  return new URLSearchParams(window.location.search).get("provider") ?? "all";
}

function artifactTitle(artifact: ArtifactData): string {
  const labels: Record<string, string> = {
    collect_csv: "Scan results export",
    collect_questions_csv: "Questions run in this scan",
    question_bank_csv: "Selected question bank",
    question_ranking_report_json: "Question ranking report",
    source_evidence_jsonl: "Source evidence export",
    report: "Visibility report",
    question_log: "Question set export",
  };
  return labels[artifact.artifact_type] ?? "Scan export";
}

function artifactMeta(artifact: ArtifactData): string {
  const format = artifact.file_format?.toUpperCase() ?? "FILE";
  if (!artifact.size_bytes) return format;
  if (artifact.size_bytes < 1024) return `${format} • ${artifact.size_bytes} B`;
  if (artifact.size_bytes < 1024 * 1024) return `${format} • ${Math.round(artifact.size_bytes / 1024)} KB`;
  return `${format} • ${(artifact.size_bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatPercent(value: number): string {
  return `${Number(value.toFixed(2))}%`;
}

function formatProvider(provider: string): string {
  if (!provider) return "AI provider";
  const labels: Record<string, string> = {
    claude: "Claude",
    gemini: "Gemini",
    openai: "OpenAI",
    perplexity: "Perplexity",
  };
  if (labels[provider.toLowerCase()]) return labels[provider.toLowerCase()];
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

function safeUrl(url?: string | null): string | null {
  if (!url) return null;
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  return null;
}

function sourcePrimaryUrl(source: GapSource): string | null {
  return source.top_urls.map(safeUrl).find((url): url is string => Boolean(url)) ?? null;
}

function citationPrimaryUrl(source: { url?: string | null }): string | null {
  return safeUrl(source.url);
}

function humanizeToken(value?: string | null): string {
  if (!value) return "Unknown";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function roleCopy(role?: string | null): string {
  const labels: Record<string, string> = {
    direct_citation_target: "Citation target",
    listing_or_profile_target: "Listing/profile",
    content_gap_signal: "Content gap",
    competitive_evidence: "Competitive evidence",
    partnership_or_pr_target: "Publisher/PR",
    monitor_only: "Monitor",
    ignore: "Ignore",
  };
  return labels[role ?? ""] ?? humanizeToken(role);
}

function sourceActionLabel(source: GapSource): string {
  if (source.action_role === "competitive_evidence") return "Review evidence";
  if (source.action_role === "content_gap_signal") return "Open cited page";
  if (source.source_type === "directory_or_review" || source.action_role === "listing_or_profile_target") {
    return `Open ${source.domain} profile`;
  }
  return "Open cited source";
}

function sourceWhy(source: GapSource): string {
  if (source.action_role === "competitive_evidence") {
    return "Competitor-owned or competitor-heavy proof. Study it, but do not treat it as a listing target.";
  }
  if (source.action_role === "content_gap_signal") {
    return "Authority or reference source shaping the answer. Use it to decide what content needs to exist on your site.";
  }
  if (source.action_role === "listing_or_profile_target") {
    return "Profile or listing source that can often be claimed, improved, or aligned with stronger proof.";
  }
  if (source.action_role === "ignore") {
    return "Low-value source captured for audit only. It is not a recommended action.";
  }
  return source.classification_reason ?? "Cited source that influenced a missed AI answer.";
}

function impactClass(impact: string): string {
  const normalized = impact.toLowerCase();
  if (normalized.includes("high")) return styles.impactHigh;
  if (normalized.includes("medium")) return styles.impactMedium;
  return styles.impactLow;
}

function providerFromFix(fix: GapFix): string | null {
  const match = fix.title.match(/\bon\s+([a-z0-9_-]+)$/i);
  return match?.[1] ?? null;
}

function formatProviderList(providers: string[]): string {
  const labels = Array.from(new Set(providers.map(formatProvider)));
  if (!labels.length) return "AI";
  if (labels.length === 1) return labels[0];
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
  return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
}

function fixKind(fix: GapFix): string {
  const text = `${fix.title} ${fix.why} ${fix.next_step}`.toLowerCase();
  if (text.includes("transactional") || text.includes("price") || text.includes("booking")) return "transactional";
  if (text.includes("concern") || text.includes("outcome") || text.includes("fit")) return "fit";
  if (text.includes("competitor") || text.includes("head-to-head") || text.includes("comparison")) return "comparison";
  if (text.includes("local") || text.includes("discovery")) return "local";
  if (text.includes("trust") || text.includes("review")) return "trust";
  if (text.includes("citation") || text.includes("source") || text.includes("listing")) return "source";
  return "general";
}

function userFacingFixTitle(fix: GapFix, clientName: string): string {
  switch (fixKind(fix)) {
    case "transactional":
      return `Price and booking questions are missing ${clientName}`;
    case "fit":
      return `${clientName} is missing from customer problem and fit questions`;
    case "comparison":
      return "Comparison questions need stronger proof";
    case "local":
      return `${clientName} is missing from local discovery questions`;
    case "trust":
      return "Trust and review questions need stronger evidence";
    case "source":
      return "Important cited sources need stronger profile proof";
    default:
      return fix.title;
  }
}

function userFacingWhy(
  fix: GapFix,
  clientName: string,
  providers: string[] = providerFromFix(fix) ? [providerFromFix(fix) as string] : [],
): string {
  const providerPrefix = providers.length
    ? `${formatProviderList(providers)} answered these questions without recommending ${clientName}. `
    : "";
  switch (fixKind(fix)) {
    case "transactional":
      return `${providerPrefix}These are high-intent questions from people checking cost, booking, availability, or what to expect before choosing.`;
    case "fit":
      return `${providerPrefix}These questions come from buyers describing a problem, desired outcome, skin type, use case, or constraint.`;
    case "comparison":
      return `${providerPrefix}AI is comparing options without enough clear proof for why someone should choose ${clientName}.`;
    case "local":
      return `${providerPrefix}AI is answering local discovery questions with other businesses or directories before ${clientName}.`;
    case "trust":
      return `${providerPrefix}AI needs stronger review, credibility, safety, and proof signals before it confidently recommends ${clientName}.`;
    case "source":
      return `${providerPrefix}AI repeatedly trusted sources where ${clientName} is missing, weak, or not clearly positioned.`;
    default:
      return fix.why;
  }
}

function userFacingNextStep(fix: GapFix): string {
  switch (fixKind(fix)) {
    case "transactional":
      return "Add clearer service pages, price ranges or pricing guidance, booking steps, FAQs, and proof for the treatments used in those questions.";
    case "fit":
      return "Add customer-problem and outcome copy: concerns, who each service is for, expected results, safety notes, and relevant FAQs.";
    case "comparison":
      return "Add comparison proof: differentiators, before/after proof, reviews, service alternatives, and pages that explain when to choose this business.";
    case "local":
      return "Improve local proof: location/service-area copy, Google/Yelp/profile consistency, local reviews, and pages that pair service plus market.";
    case "trust":
      return "Strengthen trust proof: reviews, credentials, policies, safety explanations, treatment expectations, and third-party citation signals.";
    case "source":
      return "Claim, improve, or create the profile/listing/content on the cited source if it is realistically influenceable.";
    default:
      return fix.next_step;
  }
}

function exampleQuestionForFix(fix: GapFix, missedQueries: GapQuery[]): GapQuery | null {
  const provider = providerFromFix(fix)?.toLowerCase();
  const kind = fixKind(fix);
  const matching = missedQueries.filter((query) => {
    if (provider && query.provider.toLowerCase() !== provider) return false;
    const group = `${query.group ?? ""} ${query.group_label ?? ""}`.toLowerCase();
    if (kind === "transactional") return group.includes("g4") || group.includes("transaction") || group.includes("price");
    if (kind === "fit") return group.includes("g6") || group.includes("fit") || group.includes("persona") || group.includes("concern") || group.includes("outcome");
    if (kind === "comparison") return group.includes("g3") || group.includes("g7") || group.includes("competitor") || group.includes("comparison") || query.competitors_mentioned.length > 0;
    if (kind === "local") return group.includes("g1") || group.includes("local") || group.includes("discovery");
    if (kind === "trust") return group.includes("g5") || group.includes("trust") || group.includes("review");
    return true;
  });
  const source = matching.length ? matching : missedQueries;
  return [...source].sort((a, b) => b.priority_score - a.priority_score)[0] ?? null;
}

function groupRecommendedFixes(fixes: GapFix[], clientName: string, missedQueries: GapQuery[]) {
  const groups = new Map<string, {
    evidence: string[];
    example: GapQuery | null;
    fix: GapFix;
    providers: string[];
    score: number;
    title: string;
    why: string;
    nextStep: string;
  }>();

  for (const fix of fixes) {
    const title = userFacingFixTitle(fix, clientName);
    const provider = providerFromFix(fix);
    const existing = groups.get(title);
    const evidence = provider ? `${formatProvider(provider)}: ${fix.why}` : fix.why;

    if (existing) {
      existing.evidence = Array.from(new Set([...existing.evidence, evidence]));
      existing.providers = Array.from(new Set([...existing.providers, ...(provider ? [provider] : [])]));
      existing.score += fix.score;
      if (fix.score > existing.fix.score) existing.fix = fix;
      continue;
    }

    groups.set(title, {
      evidence: [evidence],
      example: exampleQuestionForFix(fix, missedQueries),
      fix,
      providers: provider ? [provider] : [],
      score: fix.score,
      title,
      why: "",
      nextStep: userFacingNextStep(fix),
    });
  }

  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      why: userFacingWhy(group.fix, clientName, group.providers),
      example: group.example ?? exampleQuestionForFix(group.fix, missedQueries),
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);
}

export default function ResponsesPage() {
  const { entitlements } = useEntitlements();
  const rawArtifactsUnlocked = canAccessRawArtifacts(entitlements);
  const searchParams = useSearchParams();
  const scanIdParam = searchParams.get("scan_id");
  const [client, setClient] = useState<ClientData | null>(null);
  const [scan, setScan] = useState<ScanData | null>(null);
  const [citations, setCitations] = useState<CitationData[]>([]);
  const [sources, setSources] = useState<SourceProfile[]>([]);
  const [gapReport, setGapReport] = useState<GapReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ProofTab>(initialProofTab);
  const [sourceTab, setSourceTab] = useState<SourceTab>("listings");
  const [providerFilter, setProviderFilter] = useState<string>(initialProviderFilter);
  const [selectedQuery, setSelectedQuery] = useState<GapQuery | null>(null);
  const [selectedSource, setSelectedSource] = useState<GapSource | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error("Unable to load clients");
        const clients: ClientData[] = await clientsRes.json();
        const firstClient = clients[0] ?? null;
        if (!firstClient) {
          if (active) setLoading(false);
          return;
        }

        const scansRes = await fetch(`${API}/v1/clients/${firstClient.id}/scans`, {
          cache: "no-store",
        });
        if (!scansRes.ok) throw new Error("Unable to load scans");
        const scans: ScanData[] = await scansRes.json();

        // If a scan_id was provided in the URL (e.g. from scan history detail),
        // use that specific scan; otherwise fall back to the latest complete scan.
        const targetScan: ScanData | null = scanIdParam
          ? (scans.find((item) => item.id === scanIdParam) ?? null)
          : (scans.find((item) => item.status === "complete") ?? scans[0] ?? null);

        let scanDetail: ScanData | null = null;
        let citationRows: CitationData[] = [];
        let sourceRows: SourceProfile[] = [];
        let report: GapReport | null = null;
        if (targetScan) {
          const [detailRes, citationsRes, sourcesRes, gapReportRes] = await Promise.all([
            fetch(`${API}/v1/clients/${firstClient.id}/scans/${targetScan.id}`, { cache: "no-store" }),
            fetch(`${API}/v1/clients/${firstClient.id}/scans/${targetScan.id}/citations`, { cache: "no-store" }),
            fetch(`${API}/v1/clients/${firstClient.id}/sources?scan_id=${targetScan.id}&limit=40`, { cache: "no-store" }),
            fetch(`${API}/v1/clients/${firstClient.id}/gap-report?scan_id=${targetScan.id}`, { cache: "no-store" }),
          ]);
          scanDetail = detailRes.ok ? await detailRes.json() : targetScan;
          citationRows = citationsRes.ok ? await citationsRes.json() : [];
          sourceRows = sourcesRes.ok ? await sourcesRes.json() : [];
          report = gapReportRes.ok ? await gapReportRes.json() : null;
        }

        if (active) {
          setClient(firstClient);
          setScan(scanDetail);
          setCitations(citationRows);
          setSources(sourceRows);
          setGapReport(report);
          setLoading(false);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Unable to load proof data");
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [scanIdParam]);

  function selectTab(tab: ProofTab) {
    setActiveTab(tab);
    setSelectedQuery(null);
    setSelectedSource(null);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  }

  function selectProviderFilter(provider: string) {
    setProviderFilter(provider);
    setSelectedQuery(null);
    setSelectedSource(null);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (provider === "all") {
      url.searchParams.delete("provider");
    } else {
      url.searchParams.set("provider", provider);
    }
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  }

  const missedQueries = gapReport?.query_results.filter((item) => !item.appeared) ?? [];
  const clientName = client?.name ?? "your brand";
  const totalResults = gapReport?.summary.total_provider_question_results ?? 0;
  const appearanceRate = gapReport ? formatPercent(gapReport.summary.appearance_rate) : "0%";
  const fallbackActionableSources = sources.filter((source) => (
    source.action_role === "direct_citation_target"
    || source.action_role === "listing_or_profile_target"
    || source.action_role === "partnership_or_pr_target"
  )).length;
  const listingTargets = gapReport?.source_intelligence?.listing_targets ?? [];
  const directTargets = gapReport?.source_intelligence?.direct_targets ?? [];
  const publisherTargets = gapReport?.source_intelligence?.publisher_targets ?? [];
  const authorityGaps = gapReport?.source_intelligence?.authority_content_gaps ?? gapReport?.authority_content_gaps ?? [];
  const competitiveEvidence = gapReport?.source_intelligence?.competitive_evidence ?? gapReport?.competitive_evidence ?? [];
  const monitorSources = [
    ...(gapReport?.source_intelligence?.noise_sources ?? gapReport?.noise_sources ?? []),
    ...sources
      .filter((source) => source.action_role === "monitor_only" || source.action_role === "ignore")
      .map((source) => ({
        domain: source.source_domain ?? "Unknown source",
        missed_query_count: source.prompt_count,
        providers: [],
        groups: source.topics ?? [],
        example_questions: source.example_questions ?? [],
        top_urls: source.top_urls ?? [],
        owner_type: source.owner_type ?? undefined,
        source_type: source.source_type ?? undefined,
        action_role: source.action_role ?? undefined,
        actionability_score: source.actionability_score ?? undefined,
        confidence_score: source.relevance_score ?? undefined,
        classification_reason: source.classification_reason,
      })),
  ];
  const groupedSourceOpportunityCount = directTargets.length + listingTargets.length + publisherTargets.length + authorityGaps.length;
  const sourceOpportunityCount = groupedSourceOpportunityCount || gapReport?.summary.source_opportunity_count || fallbackActionableSources;
  const competitiveSources = competitiveEvidence.length || gapReport?.summary.competitive_evidence_count || sources.filter((source) => source.action_role === "competitive_evidence").length;
  const recommendedFixes = gapReport
    ? groupRecommendedFixes(gapReport.priority_fixes, clientName, missedQueries)
    : [];
  const sourceRows =
    sourceTab === "listings"
      ? [...listingTargets, ...directTargets, ...publisherTargets]
      : sourceTab === "content"
        ? authorityGaps
        : sourceTab === "competitive"
          ? competitiveEvidence
          : monitorSources;
  const providerOptions = Array.from(new Set([
    ...missedQueries.map((item) => item.provider.toLowerCase()),
    ...sourceRows.flatMap((source) => source.providers.map((provider) => provider.toLowerCase())),
  ])).sort();
  const visibleMissedQueries = providerFilter === "all"
    ? missedQueries
    : missedQueries.filter((item) => item.provider.toLowerCase() === providerFilter);
  const visibleSourceRows = providerFilter === "all"
    ? sourceRows
    : sourceRows.filter((source) => source.providers.some((provider) => provider.toLowerCase() === providerFilter));

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Responses & Proof</h1>
          <p className={styles.topCrumb}>
            {client ? `${client.name} · AI answers, citations, and gaps` : "No business profile yet"}
          </p>
        </div>
        <Link href="/onboarding" className={styles.newScanBtn}>Run new scan</Link>
      </header>

      <main className={styles.content}>
        {loading && <div className={styles.previewBanner}>Loading proof data...</div>}
        {error && <div className={styles.previewBanner}>{error}</div>}

        {!loading && !scan && (
          <div className={styles.previewBanner}>
            Run a scan to collect raw responses, artifacts, and citations.
          </div>
        )}

        {scan && (
          <>
            <section className={`${styles.card} ${styles.proofReadout}`}>
              <div className={styles.proofReadoutCopy}>
                <span className={styles.cardLabelTeal}>Scan readout</span>
                <h2>Scan takeaway</h2>
                <p>
                  {gapReport
                    ? `${clientName} appeared in ${gapReport.summary.appeared_count} of ${totalResults} tested AI answers. Start with the fixes below before running the next scan.`
                    : "AISO turns raw AI answers into clear fixes, source opportunities, and supporting evidence."}
                </p>
                {recommendedFixes[0] && (
                  <div className={styles.proofNextMove}>
                    <span>Start here</span>
                    <strong>{recommendedFixes[0].title}</strong>
                    <small>{recommendedFixes[0].nextStep}</small>
                  </div>
                )}
              </div>

              {gapReport ? (
                <div className={styles.proofMetricGrid}>
                  <div className={styles.proofMetricPrimary}>
                    <strong>{appearanceRate}</strong>
                    <span>Brand appearance rate</span>
                  </div>
                  <div>
                    <strong>{gapReport.summary.missed_count}/{totalResults}</strong>
                    <span>Missed AI answers</span>
                  </div>
                  <div>
                    <strong>{sourceOpportunityCount}</strong>
                    <span>Source opportunities</span>
                  </div>
                  <div>
                    <strong>{competitiveSources}</strong>
                    <span>Competitor proof blockers</span>
                  </div>
                </div>
              ) : (
                <p className={styles.heroSub}>
                  Gap report is waiting for a raw scan artifact. Future scans will show appeared vs missed queries here.
                </p>
              )}
            </section>

            {gapReport && (
              <>
                <nav className={styles.proofTabs} aria-label="Proof report sections">
                  {PROOF_TABS.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      className={`${styles.tabButton} ${activeTab === tab.id ? styles.tabButtonActive : ""}`}
                      onClick={() => selectTab(tab.id)}
                      aria-current={activeTab === tab.id ? "page" : undefined}
                    >
                      <span>{tab.label}</span>
                      <small>{tab.description}</small>
                    </button>
                  ))}
                </nav>

                {activeTab === "overview" && (
                  <section className={styles.proofOverviewGrid}>
                    <article className={`${styles.card} ${styles.overviewHeroCard}`}>
                      <span className={styles.cardLabelWarning}>Start here</span>
                      <h2>{recommendedFixes[0]?.title ?? "No urgent proof gaps found"}</h2>
                      <p>{recommendedFixes[0]?.why ?? "AISO did not generate a priority fix for this scan."}</p>
                      {recommendedFixes[0] && (
                        <div className={styles.overviewNextStep}>
                          <span>Recommended next step</span>
                          <strong>{recommendedFixes[0].nextStep}</strong>
                        </div>
                      )}
                      <button type="button" className={styles.primaryButton} onClick={() => selectTab("fixes")}>
                        Review fixes
                      </button>
                    </article>

                    <article className={`${styles.card} ${styles.overviewListCard}`}>
                      <div className={styles.proofSectionHeader}>
                        <div>
                          <span className={styles.cardLabelViolet}>Missed by AI</span>
                          <h2>Highest-priority missed questions</h2>
                        </div>
                        <span>{missedQueries.length} misses</span>
                      </div>
                      <div className={styles.compactEvidenceList}>
                        {missedQueries.slice(0, 5).map((item) => (
                          <button
                            key={`overview-${item.provider}-${item.group}-${item.question}`}
                            type="button"
                            className={styles.compactEvidenceRow}
                            onClick={() => setSelectedQuery(item)}
                          >
                            <span>{formatProvider(item.provider)} · {item.group}</span>
                            <strong>{item.question}</strong>
                          </button>
                        ))}
                      </div>
                      <button type="button" className={styles.secondaryButton} onClick={() => selectTab("missed")}>
                        Open missed questions
                      </button>
                    </article>

                    <article className={`${styles.card} ${styles.overviewListCard}`}>
                      <div className={styles.proofSectionHeader}>
                        <div>
                          <span className={styles.cardLabelTeal}>Source opportunities</span>
                          <h2>Best places to improve proof</h2>
                        </div>
                        <span>{sourceOpportunityCount} targets</span>
                      </div>
                      <div className={styles.compactEvidenceList}>
                        {[...listingTargets, ...directTargets].slice(0, 5).map((source) => (
                          <button
                            key={`overview-source-${source.domain}`}
                            type="button"
                            className={styles.compactEvidenceRow}
                            onClick={() => setSelectedSource(source)}
                          >
                            <span>{source.missed_query_count} missed answers</span>
                            <strong>{source.domain}</strong>
                          </button>
                        ))}
                      </div>
                      <button type="button" className={styles.secondaryButton} onClick={() => selectTab("sources")}>
                        Review source opportunities
                      </button>
                    </article>
                  </section>
                )}

                {activeTab === "fixes" && (
                  <section className={`${styles.card} ${styles.proofPanelLarge} ${styles.recommendedFixPanel}`}>
                    <div className={styles.proofSectionHeader}>
                      <div>
                        <span className={styles.cardLabelWarning}>Recommended fixes</span>
                        <h2>What to improve before the next scan</h2>
                      </div>
                      <span>{recommendedFixes.length} fixes</span>
                    </div>
                    <div className={styles.proofFixList}>
                      {recommendedFixes.length ? (
                        recommendedFixes.map(({ evidence, fix, title, why, nextStep, example, providers }) => (
                          <article key={title} className={styles.recommendedFixCard}>
                            <header className={styles.recommendedFixHeader}>
                              <div className={styles.fixTopLine}>
                                <span className={`${styles.impactBadge} ${impactClass(fix.impact)}`}>
                                  {humanizeToken(fix.impact)}
                                </span>
                                {providers.length > 0 && (
                                  <span className={styles.fixProviderPill}>
                                    {providers.map(formatProvider).join(", ")}
                                  </span>
                                )}
                              </div>
                              <div className={styles.fixSummaryBody}>
                                <div>
                                  <span className={styles.fixEyebrow}>Problem</span>
                                  <h3>{title}</h3>
                                  <p className={styles.fixNextSummary}>{nextStep}</p>
                                </div>
                              </div>
                            </header>
                            <details className={styles.fixDetails}>
                              <summary className={styles.fixDetailsSummary}>View reasoning and proof</summary>
                              <div className={styles.fixExplanationGrid}>
                                <div>
                                  <span>Why it matters</span>
                                  <p>{why}</p>
                                </div>
                              </div>
                              <div className={styles.fixEvidenceGrid}>
                                <div>
                                  <span>Evidence</span>
                                  <strong>{evidence[0]}</strong>
                                  {evidence.slice(1, 3).map((item) => (
                                    <small key={item}>{item}</small>
                                  ))}
                                </div>
                                {example && (
                                  <button type="button" className={styles.fixEvidenceButton} onClick={() => setSelectedQuery(example)}>
                                    <span>Example missed question</span>
                                    <strong>{example.question}</strong>
                                    <small>{formatProvider(example.provider)} · {example.group}</small>
                                  </button>
                                )}
                              </div>
                            </details>
                          </article>
                        ))
                      ) : (
                        <p className={styles.proofEmptyState}>
                          No priority fixes were generated for this scan yet.
                        </p>
                      )}
                    </div>
                  </section>
                )}

                {activeTab === "missed" && (
                  <section className={`${styles.card} ${styles.tablePanel}`}>
                    <div className={styles.proofSectionHeader}>
                      <div>
                        <span className={styles.cardLabelViolet}>Missed Questions</span>
                        <h2>Questions where AI did not recommend {clientName}</h2>
                      </div>
                      <span>{visibleMissedQueries.length} misses</span>
                    </div>
                    {providerOptions.length > 1 && (
                      <div className={styles.filterBar} aria-label="Filter missed questions by provider">
                        <button
                          type="button"
                          className={providerFilter === "all" ? styles.filterChipActive : styles.filterChip}
                          onClick={() => selectProviderFilter("all")}
                        >
                          All providers
                        </button>
                        {providerOptions.map((provider) => (
                          <button
                            key={`missed-filter-${provider}`}
                            type="button"
                            className={providerFilter === provider ? styles.filterChipActive : styles.filterChip}
                            onClick={() => selectProviderFilter(provider)}
                          >
                            {formatProvider(provider)}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className={styles.missedTable}>
                      <div className={styles.missedTableHeader}>
                        <span>Question</span>
                        <span>Provider</span>
                        <span>Sources cited instead</span>
                        <span>Priority</span>
                      </div>
                      {visibleMissedQueries.length ? visibleMissedQueries.map((item) => (
                        <div key={`missed-${item.provider}-${item.group}-${item.question}`} className={styles.missedTableRow}>
                          <button type="button" className={styles.tableRowButton} onClick={() => setSelectedQuery(item)}>
                            <strong>{item.question}</strong>
                            <small>{item.group_label || item.group}</small>
                          </button>
                          <span>{formatProvider(item.provider)}</span>
                          <div className={styles.sourceLinkList}>
                            {item.cited_sources.slice(0, 3).map((source, index) => {
                              const url = citationPrimaryUrl(source);
                              const label = source.domain ?? source.title ?? "Source";
                              return url ? (
                                <a key={`${item.question}-${label}-${index}`} href={url} target="_blank" rel="noopener noreferrer">
                                  {label}
                                </a>
                              ) : (
                                <span key={`${item.question}-${label}-${index}`}>{label}</span>
                              );
                            })}
                            {!item.cited_sources.length && <span>No sources captured</span>}
                          </div>
                          <strong>{Math.round(item.priority_score)}</strong>
                        </div>
                      )) : (
                        <p className={styles.proofEmptyState}>
                          No missed questions match this provider filter.
                        </p>
                      )}
                    </div>
                  </section>
                )}

                {activeTab === "sources" && (
                  <section className={`${styles.card} ${styles.tablePanel}`}>
                    <div className={styles.proofSectionHeader}>
                      <div>
                        <span className={styles.cardLabelTeal}>Source Intelligence</span>
                        <h2>Citation sources grouped by what the user can do</h2>
                      </div>
                      <span>{visibleSourceRows.length} sources</span>
                    </div>
                    <div className={styles.sourceTabs} role="tablist" aria-label="Source categories">
                      {SOURCE_TABS.map((tab) => (
                        <button
                          key={tab.id}
                          type="button"
                          className={`${styles.sourceTabButton} ${sourceTab === tab.id ? styles.sourceTabButtonActive : ""}`}
                          onClick={() => setSourceTab(tab.id)}
                        >
                          {tab.label}
                        </button>
                      ))}
                    </div>
                    {providerOptions.length > 1 && (
                      <div className={styles.filterBar} aria-label="Filter sources by provider">
                        <button
                          type="button"
                          className={providerFilter === "all" ? styles.filterChipActive : styles.filterChip}
                          onClick={() => selectProviderFilter("all")}
                        >
                          All providers
                        </button>
                        {providerOptions.map((provider) => (
                          <button
                            key={`source-filter-${provider}`}
                            type="button"
                            className={providerFilter === provider ? styles.filterChipActive : styles.filterChip}
                            onClick={() => selectProviderFilter(provider)}
                          >
                            {formatProvider(provider)}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className={styles.sourceTable}>
                      <div className={styles.sourceTableHeader}>
                        <span>Source</span>
                        <span>Role</span>
                        <span>Misses</span>
                        <span>Example</span>
                        <span>Action</span>
                      </div>
                      {visibleSourceRows.length ? visibleSourceRows.map((source, index) => {
                        const url = sourcePrimaryUrl(source);
                        return (
                          <div key={`${sourceTab}-${source.domain}-${index}`} className={styles.sourceTableRow}>
                            <button type="button" className={styles.tableRowButton} onClick={() => setSelectedSource(source)}>
                              <strong>{source.domain}</strong>
                              <small>{humanizeToken(source.source_type)}</small>
                            </button>
                            <span>{roleCopy(source.action_role)}</span>
                            <strong>{source.missed_query_count}</strong>
                            <span>{source.example_questions[0] ?? source.classification_reason ?? "No example question captured"}</span>
                            {url ? (
                              <a href={url} target="_blank" rel="noopener noreferrer">
                                {sourceActionLabel(source)}
                              </a>
                            ) : (
                              <span>No URL</span>
                            )}
                          </div>
                        );
                      }) : (
                        <p className={styles.proofEmptyState}>No sources are available in this category for the selected scan.</p>
                      )}
                    </div>
                  </section>
                )}

                {activeTab === "raw" && (
                  <section className={styles.proofLedgerGrid}>
                    <details className={`${styles.card} ${styles.proofPanelLarge} ${styles.proofLedgerDetails}`} open>
                      <summary className={styles.proofLedgerSummary}>
                        <div>
                          <span className={styles.cardLabel}>Advanced audit trail</span>
                          <h2>Raw citations and AI answer excerpts</h2>
                          <p>Use this when you need to inspect exact AI answers and every captured citation.</p>
                        </div>
                        <span>{citations.length} citations</span>
                      </summary>
                      <div className={styles.citationList}>
                        {citations.length ? (
                          citations.slice(0, 24).map((citation) => (
                            <article key={citation.id} className={styles.citationCard}>
                              <div className={styles.citationMeta}>
                                <span>
                                  {formatProvider(citation.provider)}{citation.group ? ` · ${citation.group}` : ""}
                                  {citation.web_search_used === false ? " · web-search proof missing" : ""}
                                </span>
                                <a
                                  href={citation.citation_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className={styles.citationLink}
                                >
                                  {citation.source_domain ?? citation.citation_title ?? "Open cited source"}
                                </a>
                              </div>
                              <div className={styles.proofQueryMeta}>
                                <span>{roleCopy(citation.action_role)}</span>
                                <span>{humanizeToken(citation.source_type)}</span>
                                <span>{humanizeToken(citation.owner_type)}</span>
                              </div>
                              {citation.question && (
                                <p className={styles.citationQuestion}>{citation.question}</p>
                              )}
                              {citation.answer_excerpt && (
                                <p className={styles.citationExcerpt}>{citation.answer_excerpt}</p>
                              )}
                            </article>
                          ))
                        ) : (
                          <p className={styles.heroSub}>
                            Citation rows are not available for this scan yet. Raw response artifacts are listed beside this panel.
                          </p>
                        )}
                      </div>
                    </details>

                    <aside className={`${styles.card} ${styles.proofPanelSide}`}>
                      <div className={styles.proofSectionHeader}>
                        <div>
                          <span className={styles.cardLabelTeal}>Raw exports</span>
                          <h2>Downloadable scan files</h2>
                        </div>
                      </div>
                      <p className={styles.proofPanelCopy}>
                        Use these only when you need the underlying CSV or audit artifacts. The readable report tabs are the primary workflow.
                      </p>
                      <div className={styles.actionList}>
                        {scan.artifacts?.length ? (
                          scan.artifacts.map((artifact) => (
                            <div
                              key={artifact.id}
                              className={rawArtifactsUnlocked ? styles.exportRow : styles.lockedArtifactRow}
                            >
                              <span className={styles.exportIcon}>
                                {(artifact.file_format ?? "file").slice(0, 3).toUpperCase()}
                              </span>
                              <span className={styles.exportText}>
                                <span>{artifactTitle(artifact)}</span>
                                <small>{artifactMeta(artifact)}</small>
                              </span>
                              {rawArtifactsUnlocked ? (
                                <a
                                  href={`${API}/v1/clients/${client?.id}/scans/${scan.id}/artifacts/${artifact.id}/download`}
                                  className={styles.artifactUpgradeLink}
                                >
                                  Download
                                </a>
                              ) : (
                                <>
                                  <strong className={styles.lockedBadge}>Pro export</strong>
                                  <Link href={PRO_UPGRADE_HREF} className={styles.artifactUpgradeLink}>
                                    Get it
                                  </Link>
                                </>
                              )}
                            </div>
                          ))
                        ) : (
                          <p className={styles.heroSub}>No raw response artifact has been saved for this scan.</p>
                        )}
                      </div>
                      <Link href={`/dashboard/scans/${scan.id}`} className={styles.primaryButton}>
                        Open scan detail
                      </Link>
                    </aside>
                  </section>
                )}

                {(selectedQuery || selectedSource) && (
                  <div className={styles.sidePanelLayer} role="presentation">
                    <button
                      type="button"
                      className={styles.sidePanelBackdrop}
                      aria-label="Close detail panel"
                      onClick={() => {
                        setSelectedQuery(null);
                        setSelectedSource(null);
                      }}
                    />
                    <aside className={styles.sidePanel} role="dialog" aria-modal="true">
                      <button
                        type="button"
                        className={styles.sidePanelClose}
                        onClick={() => {
                          setSelectedQuery(null);
                          setSelectedSource(null);
                        }}
                      >
                        Close
                      </button>

                      {selectedQuery && (
                        <>
                          <span className={styles.cardLabelViolet}>Missed question</span>
                          <h2>{selectedQuery.question}</h2>
                          <div className={styles.sidePanelMeta}>
                            <span>{formatProvider(selectedQuery.provider)}</span>
                            <span>{selectedQuery.group_label || selectedQuery.group}</span>
                            <span>{Math.round(selectedQuery.priority_score)} priority</span>
                          </div>
                          <div className={styles.sidePanelSection}>
                            <h3>AI cited instead</h3>
                            <div className={styles.sourceLinkList}>
                              {selectedQuery.cited_sources.map((source, index) => {
                                const url = citationPrimaryUrl(source);
                                const label = source.domain ?? source.title ?? "Source";
                                return url ? (
                                  <a key={`${label}-${index}`} href={url} target="_blank" rel="noopener noreferrer">
                                    {label}
                                  </a>
                                ) : (
                                  <span key={`${label}-${index}`}>{label}</span>
                                );
                              })}
                            </div>
                          </div>
                        </>
                      )}

                      {selectedSource && (
                        <>
                          <span className={styles.cardLabelTeal}>Source detail</span>
                          <h2>{selectedSource.domain}</h2>
                          <div className={styles.sidePanelMeta}>
                            <span>{roleCopy(selectedSource.action_role)}</span>
                            <span>{humanizeToken(selectedSource.source_type)}</span>
                            <span>{selectedSource.missed_query_count} misses</span>
                          </div>
                          <div className={styles.sidePanelSection}>
                            <h3>Why it matters</h3>
                            <p>{sourceWhy(selectedSource)}</p>
                          </div>
                          <div className={styles.sidePanelSection}>
                            <h3>Example questions</h3>
                            {selectedSource.example_questions.slice(0, 4).map((question) => (
                              <p key={question}>{question}</p>
                            ))}
                            {!selectedSource.example_questions.length && <p>No example question captured.</p>}
                          </div>
                          <div className={styles.sidePanelSection}>
                            <h3>Top URLs</h3>
                            <div className={styles.sourceLinkList}>
                              {selectedSource.top_urls.slice(0, 4).map((url) => (
                                <a key={url} href={url} target="_blank" rel="noopener noreferrer">{url}</a>
                              ))}
                              {!selectedSource.top_urls.length && <span>No source URL captured.</span>}
                            </div>
                          </div>
                        </>
                      )}
                    </aside>
                  </div>
                )}

                <p className={styles.proofFootnote}>
                  Readout based on {totalResults} provider-question results from the selected scan.
                  Rerun the scan after changing question banks or website context to refresh this evidence.
                </p>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
