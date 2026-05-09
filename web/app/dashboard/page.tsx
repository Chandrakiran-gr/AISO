"use client";

import type { CSSProperties } from "react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import styles from "./dashboard.module.css";

export const dynamic = "force-dynamic";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type ScanData = {
  id: string;
  status: string;
  providers: string[] | null;
  groups: string[] | null;
  skipped_providers?: string[] | null;
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
};

type ProviderMetric = {
  id: string;
  score: number;
  mention_count: number;
  total_questions: number;
  avg_position: number | null;
};

type GroupMetric = {
  id: string;
  label: string;
  score: number;
  mention_count: number;
  total_questions: number;
};

type CompetitorMetric = {
  name: string;
  score: number;
  mention_count: number;
  is_you: boolean;
  provider_scores?: Record<string, number>;
  provider_mentions?: Record<string, number>;
};

type MetricsData = {
  client_id: string;
  client_name: string;
  scan_id: string;
  status: string;
  overall_score: number;
  total_questions: number;
  provider_metrics: ProviderMetric[];
  group_metrics: GroupMetric[];
  competitors: CompetitorMetric[];
};

type ActionData = {
  id: string;
  title: string;
  impact_pts: string | null;
  priority: string | null;
  status: string | null;
};

type DashboardState = {
  client: ClientData | null;
  scans: ScanData[];
  metrics: MetricsData | null;
  gapReport: GapReport | null;
  actions: ActionData[];
  loading: boolean;
  error: string | null;
};

type ProviderMeta = {
  id: string;
  name: string;
  color: string;
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
};

type GapQuery = {
  question: string;
  group: string;
  group_label: string;
  provider: string;
  appeared: boolean;
  cited_sources: { domain?: string | null; url?: string | null; title?: string | null }[];
  priority_score: number;
};

type GapReport = {
  source_opportunities: GapSource[];
  query_results: GapQuery[];
};

const PROVIDERS = [
  { id: "openai", name: "ChatGPT", color: "#10a37f" },
  { id: "claude", name: "Claude", color: "#d4a27f" },
  { id: "perplexity", name: "Perplexity", color: "#1fb8cd" },
  { id: "gemini", name: "Gemini", color: "#4285f4" },
];

const PROVIDER_META = PROVIDERS.reduce<Record<string, ProviderMeta>>((map, provider) => {
  map[provider.id] = provider;
  return map;
}, {});
const PROVIDER_ORDER = PROVIDERS.map((provider) => provider.id);

function providerOrder(id: string): number {
  const index = PROVIDER_ORDER.indexOf(id);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function providerStyle(color: string, score: number): CSSProperties {
  return {
    "--provider-color": color,
    "--provider-score": `${Math.max(0, Math.min(score, 100))}%`,
  } as CSSProperties;
}

function formatProvider(id: string): string {
  return PROVIDER_META[id]?.name ?? id.charAt(0).toUpperCase() + id.slice(1);
}

function formatDate(value?: string | null): string {
  if (!value) return "No completed scans";
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ScoreRing({ score }: { score: number }) {
  const safeScore = Math.max(0, Math.min(score, 100));
  const radius = 64;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (safeScore / 100) * circumference;

  return (
    <div className={styles.scoreRingWrap} aria-label={`AI visibility score ${safeScore} out of 100`}>
      <svg className={styles.scoreRing} viewBox="0 0 160 160" role="img">
        <defs>
          <linearGradient id="visibilityGradient" x1="20" y1="140" x2="142" y2="22">
            <stop offset="0%" stopColor="#00d4aa" />
            <stop offset="100%" stopColor="#7c5cfc" />
          </linearGradient>
        </defs>
        <circle className={styles.scoreRingBase} cx="80" cy="80" r={radius} />
        <circle
          className={styles.scoreRingValue}
          cx="80"
          cy="80"
          r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className={styles.scoreCenter}>
        <span className={styles.scoreNumber}>{Math.round(safeScore)}</span>
        <span className={styles.scoreDenominator}>/100</span>
      </div>
    </div>
  );
}

function ProviderCard({
  provider,
  metric,
  selected = false,
  onSelect,
}: {
  provider: ProviderMeta;
  metric?: ProviderMetric;
  selected?: boolean;
  onSelect: () => void;
}) {
  const score = metric?.score ?? 0;
  return (
    <button
      type="button"
      className={`${styles.providerCard} ${selected ? styles.providerCardSelected : ""}`}
      style={providerStyle(provider.color, score)}
      onClick={onSelect}
      aria-expanded={selected}
      aria-label={`Open ${provider.name} provider breakdown`}
    >
      <div className={styles.providerHeader}>
        <span className={styles.providerDot} />
        <span className={styles.providerName}>{provider.name}</span>
      </div>
      <div className={styles.providerMetric}>
        <span className={styles.providerScore}>{Math.round(score)}</span>
        <span className={styles.providerOutOf}>/100</span>
      </div>
      <span className={styles.providerTrack}>
        <span className={styles.providerFill} />
      </span>
      <p className={styles.heroSub}>
        {metric
          ? `${metric.mention_count}/${metric.total_questions} mentions`
          : "No completed scan data"}
      </p>
      <span className={styles.providerCardHint}>View breakdown</span>
    </button>
  );
}

function CompetitorRow({
  competitor,
  rank,
  selected,
  onSelect,
}: {
  competitor: CompetitorMetric;
  rank: number;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`${styles.competitorRow} ${selected ? styles.competitorRowSelected : ""}`}
      onClick={onSelect}
      aria-expanded={selected}
      title={competitor.is_you ? "Your Business" : competitor.name}
    >
      <span className={styles.competitorRank}>#{rank}</span>
      <span className={styles.competitorName}>
        {competitor.is_you ? "Your Business" : competitor.name}
      </span>
      <span className={styles.competitorTrack}>
        <span
          className={`${styles.competitorFill} ${competitor.is_you ? styles.gradientFill : ""}`}
          style={{
            "--competitor-color": competitor.is_you ? "#00d4aa" : "#ffd93d",
            "--competitor-score": `${Math.max(0, Math.min(competitor.score, 100))}%`,
          } as CSSProperties}
        />
      </span>
      <span className={styles.competitorMentions}>{competitor.mention_count} mentions</span>
      <span className={styles.competitorScore}>{Math.round(competitor.score)}</span>
    </button>
  );
}

export default function DashboardPage() {
  const [state, setState] = useState<DashboardState>({
    client: null,
    scans: [],
    metrics: null,
    gapReport: null,
    actions: [],
    loading: true,
    error: null,
  });
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);
  const [selectedCompetitorName, setSelectedCompetitorName] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error("Unable to load clients");

        const clients: ClientData[] = await clientsRes.json();
        const client = clients[0] ?? null;
        if (!client) {
          if (active) {
            setState((prev) => ({ ...prev, client: null, loading: false }));
          }
          return;
        }

        const scansRes = await fetch(`${API}/v1/clients/${client.id}/scans`, { cache: "no-store" });
        if (!scansRes.ok) throw new Error("Unable to load scans");
        const scans: ScanData[] = await scansRes.json();
        const latestComplete = scans.find((scan) => scan.status === "complete") ?? scans[0] ?? null;
        const [metricsRes, actionsRes, gapReportRes] = await Promise.all([
          fetch(`${API}/v1/clients/${client.id}/metrics`, { cache: "no-store" }),
          fetch(`${API}/v1/clients/${client.id}/actions?status=open`, { cache: "no-store" }),
          latestComplete
            ? fetch(`${API}/v1/clients/${client.id}/gap-report?scan_id=${latestComplete.id}`, { cache: "no-store" })
            : Promise.resolve(null),
        ]);

        const metrics: MetricsData | null = metricsRes.ok ? await metricsRes.json() : null;
        const actions: ActionData[] = actionsRes.ok ? await actionsRes.json() : [];
        const gapReport: GapReport | null = gapReportRes && gapReportRes.ok ? await gapReportRes.json() : null;

        if (active) {
          setState({
            client,
            scans,
            metrics,
            gapReport,
            actions,
            loading: false,
            error: null,
          });
        }
      } catch (error) {
        if (active) {
          setState((prev) => ({
            ...prev,
            loading: false,
            error: error instanceof Error ? error.message : "Unable to load dashboard",
          }));
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, []);

  const latestScan = state.scans[0] ?? null;
  const scanRunning = latestScan?.status === "running" || latestScan?.status === "pending";
  const failedScan = latestScan?.status === "failed" ? latestScan : null;
  const providerMetrics = useMemo(() => {
    const map = new Map<string, ProviderMetric>();
    state.metrics?.provider_metrics.forEach((metric) => map.set(metric.id, metric));
    return map;
  }, [state.metrics]);
  const topCompetitors = state.metrics?.competitors.slice(0, 4) ?? [];
  const topActions = state.actions.filter((action) => (action.status ?? "open") === "open").slice(0, 3);
  const visibleProviders = state.metrics
    ? state.metrics.provider_metrics
        .slice()
        .sort((a, b) => providerOrder(a.id) - providerOrder(b.id))
        .map((metric) => (
          PROVIDER_META[metric.id] ?? {
            id: metric.id,
            name: metric.id,
            color: "#8b94a7",
          }
        ))
    : PROVIDERS;
  const selectedProvider = selectedProviderId
    ? visibleProviders.find((provider) => provider.id === selectedProviderId) ?? null
    : null;
  const selectedProviderMetric = selectedProvider ? providerMetrics.get(selectedProvider.id) : undefined;
  const selectedProviderMisses = state.gapReport?.query_results
    .filter((query) => query.provider.toLowerCase() === selectedProvider?.id.toLowerCase() && !query.appeared)
    .slice()
    .sort((a, b) => b.priority_score - a.priority_score)
    .slice(0, 5) ?? [];
  const selectedProviderSources = state.gapReport?.source_opportunities
    .filter((source) => source.providers.some((provider) => provider.toLowerCase() === selectedProvider?.id.toLowerCase()))
    .slice(0, 5) ?? [];
  const selectedCompetitor = selectedCompetitorName
    ? topCompetitors.find((competitor) => competitor.name === selectedCompetitorName) ?? null
    : null;

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Dashboard</h1>
          <p className={styles.topCrumb}>
            {state.loading
              ? "Loading..."
              : state.client
                ? `${state.client.name} · ${formatDate(latestScan?.completed_at ?? latestScan?.created_at)}`
                : "Create your first business profile"}
          </p>
        </div>
        <div className={styles.topActions}>
          <Link href="/onboarding" className={styles.newScanBtn}>Run new scan</Link>
        </div>
      </header>

      <main className={styles.content}>
        <section className={styles.hero}>
          <div>
            <h2 className={styles.heroTitle}>
              {state.client
                ? `What AI is saying about ${state.client.name}`
                : "Set up your first AI visibility scan"}
            </h2>
            <p className={styles.heroSub}>
              {state.metrics
                ? `${state.metrics.total_questions} provider-question results analyzed from the latest completed scan.`
                : "Run a scan to see visibility, competitor gaps, citations, and prioritized next steps."}
            </p>
          </div>
          <Link href="/onboarding" className={styles.newScanBtn}>
            {state.client ? "Run new scan" : "Start onboarding"}
          </Link>
        </section>

        {state.error && <div className={styles.previewBanner}>{state.error}</div>}

        {scanRunning && (
          <div className={styles.scanBanner}>
            <span className={styles.scanBannerSpinner} aria-hidden="true" />
            <p>
              <strong>Scan in progress</strong> — querying AI platforms across the selected question set.
            </p>
          </div>
        )}

        {failedScan && (
          <div className={styles.previewBanner}>
            Latest scan failed: {failedScan.error || "Check provider keys and try again."}
          </div>
        )}

        {!state.loading && state.client && !state.metrics && !scanRunning && !failedScan && (
          <div className={styles.previewBanner}>
            No completed scan metrics yet. Run your first scan to populate the dashboard.
          </div>
        )}

        <section className={styles.summaryGrid}>
          <article className={`${styles.card} ${styles.scoreCard}`}>
            <span className={styles.cardLabelTeal}>Overall score</span>
            <ScoreRing score={state.metrics?.overall_score ?? 0} />
            <p className={styles.scoreCaption}>AI Visibility Score</p>
            <Link href="/dashboard/responses" className={styles.proofCta}>View proof report</Link>
          </article>

          <article className={`${styles.card} ${styles.urgencyCard}`}>
            <span className={styles.cardLabelWarning}>Intent gaps</span>
            <strong className={styles.gapMetric}>
              {state.metrics?.group_metrics.length ?? 0}
            </strong>
            <p className={styles.gapCopy}>intent groups measured in the latest scan</p>
            <div className={styles.cardDivider} />
            <span className={styles.smallMuted}>Weakest group</span>
            <div className={styles.nextMoveRow}>
              <strong>
                {state.metrics?.group_metrics
                  .slice()
                  .sort((a, b) => a.score - b.score)[0]?.label ?? "Waiting for scan data"}
              </strong>
              <Link href="/dashboard/actions" className={styles.primaryButton}>Open actions</Link>
            </div>
          </article>

          <article className={`${styles.card} ${styles.competitorCard}`}>
            <span className={styles.cardLabelViolet}>Top competitors</span>
            <div className={styles.competitorList}>
              {topCompetitors.length ? (
                topCompetitors.map((competitor, index) => (
                  <CompetitorRow
                    key={`${competitor.name}-${competitor.is_you}`}
                    competitor={competitor}
                    rank={index + 1}
                    selected={selectedCompetitorName === competitor.name}
                    onSelect={() => {
                      setSelectedCompetitorName(competitor.name);
                      setSelectedProviderId(null);
                    }}
                  />
                ))
              ) : (
                <p className={styles.heroSub}>Competitor metrics will appear after a completed scan.</p>
              )}
            </div>
            <Link href="/dashboard/competitors" className={styles.secondaryButton}>View comparison</Link>
          </article>
        </section>

        <section aria-labelledby="providers-heading">
          <h2 id="providers-heading" className={styles.sectionLabel}>Provider breakdown</h2>
          <div className={styles.providerGrid}>
            {visibleProviders.map((provider) => (
              <ProviderCard
                key={provider.id}
                provider={provider}
                metric={providerMetrics.get(provider.id)}
                selected={selectedProviderId === provider.id}
                onSelect={() => {
                  setSelectedProviderId(provider.id);
                  setSelectedCompetitorName(null);
                }}
              />
            ))}
          </div>
        </section>

        {(selectedProvider || selectedCompetitor) && (
          <div className={styles.sidePanelLayer} role="presentation">
            <button
              type="button"
              className={styles.sidePanelBackdrop}
              aria-label="Close dashboard detail panel"
              onClick={() => {
                setSelectedProviderId(null);
                setSelectedCompetitorName(null);
              }}
            />
            <aside className={styles.sidePanel} role="dialog" aria-modal="true">
              <button
                type="button"
                className={styles.sidePanelClose}
                onClick={() => {
                  setSelectedProviderId(null);
                  setSelectedCompetitorName(null);
                }}
              >
                Close
              </button>

              {selectedProvider && (
                <>
                  <span className={styles.cardLabelTeal}>Provider breakdown</span>
                  <h2>{selectedProvider.name}</h2>
                  <p className={styles.heroSub}>
                    {selectedProviderMetric
                      ? `${selectedProviderMetric.mention_count} of ${selectedProviderMetric.total_questions} answers mentioned ${state.client?.name ?? "your brand"}.`
                      : "Provider metrics will appear after a completed scan."}
                  </p>
                  <div className={styles.sidePanelMeta}>
                    <span>{Math.round(selectedProviderMetric?.score ?? 0)} score</span>
                    <span>{selectedProviderMetric ? selectedProviderMetric.total_questions - selectedProviderMetric.mention_count : 0} misses</span>
                    <span>{selectedProviderSources.length} sources</span>
                  </div>
                  <div className={styles.sidePanelSection}>
                    <h3>Highest-priority missed questions</h3>
                    {selectedProviderMisses.length ? selectedProviderMisses.map((query) => (
                      <Link
                        key={`${query.provider}-${query.group}-${query.question}`}
                        href={`/dashboard/responses?tab=missed&provider=${selectedProvider.id}`}
                        className={styles.drilldownRow}
                      >
                        <span>{query.group_label || query.group}</span>
                        <strong>{query.question}</strong>
                      </Link>
                    )) : (
                      <p>No missed questions were isolated for this provider.</p>
                    )}
                  </div>
                  <div className={styles.sidePanelSection}>
                    <h3>Top cited sources</h3>
                    {selectedProviderSources.length ? selectedProviderSources.map((source) => (
                      <Link
                        key={`${selectedProvider.id}-${source.domain}`}
                        href={`/dashboard/responses?tab=sources&provider=${selectedProvider.id}`}
                        className={styles.drilldownRowCompact}
                      >
                        <strong>{source.domain}</strong>
                        <span>{source.missed_query_count} misses</span>
                      </Link>
                    )) : (
                      <p>Source opportunities will appear after evidence is available.</p>
                    )}
                  </div>
                </>
              )}

              {selectedCompetitor && (
                <>
                  <span className={styles.cardLabelViolet}>Competitor breakdown</span>
                  <h2>{selectedCompetitor.is_you ? "Your Business" : selectedCompetitor.name}</h2>
                  <p className={styles.heroSub}>Compare mention share and provider-level pressure before opening the full competitor report.</p>
                  <div className={styles.sidePanelMeta}>
                    <span>{Math.round(selectedCompetitor.score)} overall</span>
                    <span>{selectedCompetitor.mention_count} mentions</span>
                    <span>{Object.keys(selectedCompetitor.provider_scores ?? {}).length} providers</span>
                  </div>
                  <div className={styles.sidePanelSection}>
                    <h3>Provider scores</h3>
                    <div className={styles.providerScoreTable}>
                      {visibleProviders.map((provider) => (
                        <div key={`${selectedCompetitor.name}-${provider.id}`}>
                          <span>{formatProvider(provider.id)}</span>
                          <strong>{Math.round(selectedCompetitor.provider_scores?.[provider.id] ?? 0)}</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                  <Link href="/dashboard/competitors" className={styles.primaryButton}>Open full comparison</Link>
                </>
              )}
            </aside>
          </div>
        )}

        <section className={styles.dashboardActionGrid}>
          <article className={`${styles.card} ${styles.actionsCard}`}>
            <span className={styles.cardLabelTeal}>Priority actions</span>
            <p className={styles.actionSummary}>
              {topActions.length
                ? `${topActions.length} open recommendations from latest scans`
                : "Recommendations appear after a completed scan"}
            </p>
            <div className={styles.actionList}>
              {topActions.map((action) => (
                <div key={action.id} className={styles.actionRow}>
                  <span className={styles.actionDot} />
                  <span>{action.title}</span>
                  <strong>{action.impact_pts ?? "Review"}</strong>
                </div>
              ))}
            </div>
            <Link href="/dashboard/actions" className={styles.primaryButton}>Open actions</Link>
          </article>
        </section>

        <p className={styles.scanMeta}>
          Latest scan: {latestScan ? latestScan.status : "none"}
          {latestScan?.providers?.length ? ` · ${latestScan.providers.length} platforms` : ""}
        </p>
      </main>
    </div>
  );
}
