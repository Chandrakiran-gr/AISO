"use client";

import type { CSSProperties } from "react";
import Link from "next/link";
import { useMemo, useState } from "react";
import styles from "./dashboard.module.css";

export type ProviderMetric = {
  id: string;
  score: number;
  mention_count: number;
  total_questions: number;
  avg_position: number | null;
};

export type GroupMetric = {
  id: string;
  label: string;
  score: number;
  mention_count: number;
  total_questions: number;
};

export type CompetitorMetric = {
  name: string;
  score: number;
  mention_count: number;
  is_you: boolean;
  provider_scores?: Record<string, number>;
  provider_mentions?: Record<string, number>;
};

export type MetricsData = {
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

export type ActionData = {
  id: string;
  title: string;
  impact_pts: string | null;
  priority: string | null;
  status: string | null;
};

export type GapSource = {
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

export type GapQuery = {
  question: string;
  group: string;
  group_label: string;
  provider: string;
  appeared: boolean;
  cited_sources: { domain?: string | null; url?: string | null; title?: string | null }[];
  priority_score: number;
};

export type GapReport = {
  source_opportunities: GapSource[];
  query_results: GapQuery[];
};

type ProviderMeta = {
  id: string;
  name: string;
  color: string;
};

type DashboardOverviewProps = {
  clientName?: string | null;
  metrics: MetricsData | null;
  gapReport: GapReport | null;
  actions: ActionData[];
  actionScopeLabel?: string;
  metricScopeLabel?: string;
  scanMetaLabel?: string | null;
  /** When set, all links to /dashboard/responses include ?scan_id= so the
   *  responses page loads data for this specific historical scan. */
  scanId?: string | null;
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

function formatProvider(id: string): string {
  return PROVIDER_META[id]?.name ?? id.charAt(0).toUpperCase() + id.slice(1);
}

function CompetitorRow({
  competitor,
  rank,
  selected,
  onSelect,
  ownBusinessName,
}: {
  competitor: CompetitorMetric;
  rank: number;
  selected: boolean;
  onSelect: () => void;
  ownBusinessName: string;
}) {
  const displayName = competitor.is_you ? ownBusinessName : competitor.name;

  return (
    <button
      type="button"
      className={`${styles.competitorRow} ${selected ? styles.competitorRowSelected : ""}`}
      onClick={onSelect}
      aria-expanded={selected}
      title={displayName}
    >
      <span className={styles.competitorRank}>#{rank}</span>
      <span className={styles.competitorIdentity}>
        <strong>{displayName}</strong>
        <small>{competitor.mention_count} mentions</small>
      </span>
      <span className={styles.competitorScore}>{Math.round(competitor.score)}</span>
      <span className={styles.competitorTrack}>
        <span
          className={`${styles.competitorFill} ${competitor.is_you ? styles.gradientFill : ""}`}
          style={{
            "--competitor-color": competitor.is_you ? "#8f95ff" : "#f6c177",
            "--competitor-score": `${Math.max(0, Math.min(competitor.score, 100))}%`,
          } as CSSProperties}
        />
      </span>
    </button>
  );
}

export function DashboardOverview({
  clientName,
  metrics,
  gapReport,
  actions,
  actionScopeLabel = "latest scans",
  metricScopeLabel = "latest scan",
  scanMetaLabel,
  scanId,
}: DashboardOverviewProps) {
  function responsesHref(extraParams?: string): string {
    const base = "/dashboard/responses";
    const parts: string[] = [];
    if (scanId) parts.push(`scan_id=${encodeURIComponent(scanId)}`);
    if (extraParams) parts.push(extraParams);
    return parts.length ? `${base}?${parts.join("&")}` : base;
  }
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);
  const [selectedCompetitorName, setSelectedCompetitorName] = useState<string | null>(null);
  const providerMetrics = useMemo(() => {
    const map = new Map<string, ProviderMetric>();
    metrics?.provider_metrics.forEach((metric) => map.set(metric.id, metric));
    return map;
  }, [metrics]);
  const topCompetitors = metrics?.competitors.slice(0, 4) ?? [];
  const topActions = actions.filter((action) => (action.status ?? "open") === "open").slice(0, 3);
  const visibleProviders = metrics
    ? metrics.provider_metrics
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
  const selectedProviderMisses = gapReport?.query_results
    .filter((query) => query.provider.toLowerCase() === selectedProvider?.id.toLowerCase() && !query.appeared)
    .slice()
    .sort((a, b) => b.priority_score - a.priority_score)
    .slice(0, 5) ?? [];
  const selectedProviderSources = gapReport?.source_opportunities
    .filter((source) => source.providers.some((provider) => provider.toLowerCase() === selectedProvider?.id.toLowerCase()))
    .slice(0, 5) ?? [];
  const selectedCompetitor = selectedCompetitorName
    ? topCompetitors.find((competitor) => competitor.name === selectedCompetitorName) ?? null
    : null;
  const matrixGroups = useMemo(() => {
    const groups = new Map<string, string>();
    gapReport?.query_results.forEach((query) => {
      groups.set(query.group.toLowerCase(), query.group_label || query.group);
    });
    metrics?.group_metrics.forEach((metric) => {
      if (!groups.has(metric.id.toLowerCase())) {
        groups.set(metric.id.toLowerCase(), metric.label);
      }
    });
    return Array.from(groups, ([id, label]) => ({ id, label })).slice(0, 7);
  }, [gapReport, metrics]);
  const groupMetrics = useMemo(() => {
    const map = new Map<string, GroupMetric>();
    metrics?.group_metrics.forEach((metric) => map.set(metric.id.toLowerCase(), metric));
    return map;
  }, [metrics]);
  const weakestGroup = metrics?.group_metrics
    .slice()
    .sort((a, b) => a.score - b.score)[0];
  const totalMentions = metrics?.provider_metrics.reduce((sum, metric) => sum + metric.mention_count, 0) ?? 0;
  const totalQuestions = metrics?.provider_metrics.reduce((sum, metric) => sum + metric.total_questions, 0) ?? 0;
  const missedCount = Math.max(0, totalQuestions - totalMentions);
  const overallScore = Math.round(metrics?.overall_score ?? 0);
  const overallScorePercent = Math.max(0, Math.min(overallScore, 100));
  const competitorLeader = topCompetitors[0] ?? null;
  const ownCompetitor = topCompetitors.find((competitor) => competitor.is_you) ?? null;
  const strongestOtherCompetitor = topCompetitors
    .filter((competitor) => !competitor.is_you)
    .slice()
    .sort((a, b) => b.score - a.score)[0] ?? null;
  const competitorDelta =
    ownCompetitor && strongestOtherCompetitor
      ? Math.round(ownCompetitor.score - strongestOtherCompetitor.score)
      : null;
  const ownMetricName = ownCompetitor?.name?.trim();
  const ownBusinessName =
    clientName?.trim()
    || (ownMetricName && !/^your business$/i.test(ownMetricName) ? ownMetricName : "Current business");

  function matrixCell(providerId: string, groupId: string) {
    const rows = gapReport?.query_results.filter((query) => (
      query.provider.toLowerCase() === providerId.toLowerCase()
      && query.group.toLowerCase() === groupId.toLowerCase()
    )) ?? [];

    if (rows.length) {
      const mentions = rows.filter((query) => query.appeared).length;
      return {
        empty: false,
        mentions,
        score: Math.round((mentions / rows.length) * 100),
        total: rows.length,
      };
    }

    const fallback = groupMetrics.get(groupId.toLowerCase());
    return {
      empty: !fallback,
      mentions: fallback?.mention_count ?? 0,
      score: Math.round(fallback?.score ?? 0),
      total: fallback?.total_questions ?? 0,
    };
  }

  return (
    <>
      <section className={styles.consoleGrid} aria-label="AI visibility command summary">
        <article className={styles.scoreConsolePanel}>
          <div className={styles.scoreConsoleHeader}>
            <span className={styles.cardLabelTeal}>AI visibility</span>
            <small>{totalQuestions ? `${totalMentions}/${totalQuestions} answers` : "No scan data"}</small>
          </div>
          <div className={styles.scoreHeadline}>
            <strong>{overallScore}</strong>
            <span>/100</span>
          </div>
          <div className={styles.scoreSignalTrack} aria-hidden="true">
            <span style={{ "--score-percent": `${overallScorePercent}%` } as CSSProperties} />
          </div>
          <div className={styles.scoreMicroStats}>
            <span>
              <strong>{totalMentions}</strong>
              Mentions
            </span>
            <span>
              <strong>{missedCount}</strong>
              Misses
            </span>
          </div>
          <Link href={responsesHref()} className={styles.proofCta}>Open proof</Link>
        </article>

        <article className={styles.consoleReadoutPanel}>
          <div className={styles.consoleReadoutHeader}>
            <div>
              <span className={styles.cardLabel}>Latest scan readout</span>
              <h2>{clientName ? `${clientName} evidence summary` : "Evidence summary"}</h2>
            </div>
            <Link href="/dashboard/actions" className={styles.secondaryButton}>Open action queue</Link>
          </div>
          <div className={styles.consoleStatsRow}>
            <span>
              <strong>{totalMentions}</strong>
              Mentions
            </span>
            <span>
              <strong>{missedCount}</strong>
              Misses
            </span>
            <span>
              <strong>{matrixGroups.length || metrics?.group_metrics.length || 0}</strong>
              Intent groups
            </span>
            <span>
              <strong>{topActions.length}</strong>
              Open actions
            </span>
          </div>
          <div className={styles.weakestSignalRow}>
            <span>Weakest signal</span>
            <strong>{weakestGroup?.label ?? "Waiting for scan data"}</strong>
            <small>{weakestGroup ? `${Math.round(weakestGroup.score)}/100 across this group` : metricScopeLabel}</small>
          </div>
        </article>

        <article className={styles.competitorConsolePanel}>
          <div className={styles.consoleReadoutHeader}>
            <div>
              <span className={styles.cardLabelViolet}>Competitor pressure</span>
              <h2>Top mentions</h2>
            </div>
            <Link href="/dashboard/competitors" className={styles.secondaryButton}>Compare</Link>
          </div>
          {competitorLeader ? (
            <div className={styles.competitorInsight}>
              <span>Leader</span>
              <strong>{competitorLeader.is_you ? ownBusinessName : competitorLeader.name}</strong>
              <small>
                {competitorDelta !== null
                  ? `${competitorDelta >= 0 ? "+" : ""}${competitorDelta} pts vs ${strongestOtherCompetitor?.name}`
                  : `${competitorLeader.mention_count} mentions captured`}
              </small>
            </div>
          ) : null}
          <div className={styles.competitorList}>
            {topCompetitors.length ? (
              topCompetitors.map((competitor, index) => (
                <CompetitorRow
                  key={`${competitor.name}-${competitor.is_you}`}
                  competitor={competitor}
                  rank={index + 1}
                  selected={selectedCompetitorName === competitor.name}
                  ownBusinessName={ownBusinessName}
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
        </article>
      </section>

      <section className={styles.matrixPanel} aria-labelledby="providers-heading">
        <div className={styles.matrixHeader}>
          <div>
            <span className={styles.sectionLabel}>Provider x Intent Evidence Matrix</span>
            <h2 id="providers-heading">Where AI sees the brand, and where it misses</h2>
          </div>
          <Link href={responsesHref()} className={styles.secondaryButton}>Review responses</Link>
        </div>
        <div className={styles.matrixScroller}>
          <div
            className={styles.evidenceMatrix}
            style={{ "--matrix-columns": Math.max(1, matrixGroups.length) } as CSSProperties}
          >
            <div className={`${styles.matrixCell} ${styles.matrixCorner}`}>Provider</div>
            {matrixGroups.map((group) => (
              <div key={`matrix-head-${group.id}`} className={`${styles.matrixCell} ${styles.matrixHead}`}>
                {group.label}
              </div>
            ))}
            {!matrixGroups.length && (
              <div className={`${styles.matrixCell} ${styles.matrixHead}`}>No intent data</div>
            )}

            {visibleProviders.map((provider) => {
              const metric = providerMetrics.get(provider.id);
              return (
                <div key={`matrix-row-${provider.id}`} className={styles.matrixRow}>
                  <button
                    type="button"
                    className={`${styles.matrixProviderCell} ${selectedProviderId === provider.id ? styles.matrixProviderCellActive : ""}`}
                    onClick={() => {
                      setSelectedProviderId(provider.id);
                      setSelectedCompetitorName(null);
                    }}
                  >
                    <span className={styles.providerDot} style={{ "--provider-color": provider.color } as CSSProperties} />
                    <strong>{provider.name}</strong>
                    <small>{metric ? `${metric.mention_count}/${metric.total_questions} mentions` : "No data"}</small>
                  </button>
                  {(matrixGroups.length ? matrixGroups : [{ id: "none", label: "No intent data" }]).map((group) => {
                    const cell = group.id === "none" ? { empty: true, mentions: 0, score: 0, total: 0 } : matrixCell(provider.id, group.id);
                    return (
                      <button
                        key={`matrix-${provider.id}-${group.id}`}
                        type="button"
                        className={`${styles.matrixIntentCell} ${cell.empty ? styles.matrixIntentCellEmpty : ""}`}
                        onClick={() => {
                          setSelectedProviderId(provider.id);
                          setSelectedCompetitorName(null);
                        }}
                        style={{ "--cell-score": `${cell.score}%` } as CSSProperties}
                        aria-label={`${provider.name} ${group.label}: ${cell.empty ? "no data" : `${cell.score} percent appearance rate`}`}
                      >
                        <strong>{cell.empty ? "—" : `${cell.score}`}</strong>
                        <span>{cell.empty ? "No data" : `${cell.mentions}/${cell.total}`}</span>
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
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
                    ? `${selectedProviderMetric.mention_count} of ${selectedProviderMetric.total_questions} answers mentioned ${clientName ?? "your brand"}.`
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
                      href={responsesHref(`tab=missed&provider=${selectedProvider.id}`)}
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
                      href={responsesHref(`tab=sources&provider=${selectedProvider.id}`)}
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
                <h2>{selectedCompetitor.is_you ? ownBusinessName : selectedCompetitor.name}</h2>
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
              ? `${topActions.length} open recommendations from ${actionScopeLabel}`
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

      {scanMetaLabel && <p className={styles.scanMeta}>{scanMetaLabel}</p>}
    </>
  );
}
