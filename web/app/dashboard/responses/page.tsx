"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { CURRENT_PLAN, PRO_UPGRADE_HREF, canAccessRawArtifacts } from "@/lib/plan";
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
};

type GapSource = {
  domain: string;
  missed_query_count: number;
  providers: string[];
  groups: string[];
  example_questions: string[];
  top_urls: string[];
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
  };
  priority_fixes: GapFix[];
  source_opportunities: GapSource[];
  query_results: GapQuery[];
};

function artifactTitle(artifact: ArtifactData): string {
  const labels: Record<string, string> = {
    collect_csv: "Scan results export",
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
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

function compactDomainList(
  sources: { domain?: string | null; url?: string | null; title?: string | null }[],
): string {
  const labels = sources
    .map((source) => source.domain ?? source.title)
    .filter((label): label is string => Boolean(label));
  const uniqueLabels = Array.from(new Set(labels));
  if (!uniqueLabels.length) return "No sources captured";
  return uniqueLabels.slice(0, 3).join(", ");
}

function impactClass(impact: string): string {
  const normalized = impact.toLowerCase();
  if (normalized.includes("high")) return styles.impactHigh;
  if (normalized.includes("medium")) return styles.impactMedium;
  return styles.impactLow;
}

export default function ResponsesPage() {
  const { data: session } = useSession();
  const rawArtifactsUnlocked = canAccessRawArtifacts(CURRENT_PLAN, session?.user?.email);
  const [client, setClient] = useState<ClientData | null>(null);
  const [scan, setScan] = useState<ScanData | null>(null);
  const [citations, setCitations] = useState<CitationData[]>([]);
  const [gapReport, setGapReport] = useState<GapReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
        const latestComplete = scans.find((item) => item.status === "complete") ?? scans[0] ?? null;

        let scanDetail: ScanData | null = null;
        let citationRows: CitationData[] = [];
        let report: GapReport | null = null;
        if (latestComplete) {
          const [detailRes, citationsRes, gapReportRes] = await Promise.all([
            fetch(`${API}/v1/clients/${firstClient.id}/scans/${latestComplete.id}`, { cache: "no-store" }),
            fetch(`${API}/v1/clients/${firstClient.id}/scans/${latestComplete.id}/citations`, { cache: "no-store" }),
            fetch(`${API}/v1/clients/${firstClient.id}/gap-report?scan_id=${latestComplete.id}`, { cache: "no-store" }),
          ]);
          scanDetail = detailRes.ok ? await detailRes.json() : latestComplete;
          citationRows = citationsRes.ok ? await citationsRes.json() : [];
          report = gapReportRes.ok ? await gapReportRes.json() : null;
        }

        if (active) {
          setClient(firstClient);
          setScan(scanDetail);
          setCitations(citationRows);
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
  }, []);

  const missedQueries = gapReport?.query_results.filter((item) => !item.appeared) ?? [];
  const topFix = gapReport?.priority_fixes[0] ?? null;
  const appearedCount = gapReport?.summary.appeared_count ?? 0;
  const missedCount = gapReport?.summary.missed_count ?? 0;
  const totalResults = gapReport?.summary.total_provider_question_results ?? 0;
  const appearanceRate = gapReport ? formatPercent(gapReport.summary.appearance_rate) : "0%";

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
                <h2>What AI answers did with your brand</h2>
                <p>
                  This page separates the scan into four decisions: where AI mentioned you,
                  where it skipped you, which sources it trusted instead, and what to fix next.
                </p>
                {topFix && (
                  <div className={styles.proofNextMove}>
                    <span>Highest priority</span>
                    <strong>{topFix.title}</strong>
                  </div>
                )}
              </div>

              {gapReport ? (
                <div className={styles.proofMetricGrid}>
                  <div className={styles.proofMetricPrimary}>
                    <strong>{appearanceRate}</strong>
                    <span>AI visibility in this scan</span>
                  </div>
                  <div>
                    <strong>{appearedCount}</strong>
                    <span>Mentioned you</span>
                  </div>
                  <div>
                    <strong>{missedCount}</strong>
                    <span>Skipped you</span>
                  </div>
                  <div>
                    <strong>{gapReport.summary.source_opportunity_count}</strong>
                    <span>Sources cited instead</span>
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
                <section className={styles.proofExplainGrid}>
                  <div className={styles.proofExplainItem}>
                    <span className={styles.proofExplainDotGood} />
                    <div>
                      <strong>Appeared</strong>
                      <p>AI mentioned {client?.name ?? "your brand"} in the answer.</p>
                    </div>
                  </div>
                  <div className={styles.proofExplainItem}>
                    <span className={styles.proofExplainDotRisk} />
                    <div>
                      <strong>Missed</strong>
                      <p>AI answered the buyer question but did not mention you.</p>
                    </div>
                  </div>
                  <div className={styles.proofExplainItem}>
                    <span className={styles.proofExplainDotSource} />
                    <div>
                      <strong>Cited instead</strong>
                      <p>These domains are the proof layer AI trusted while you were absent.</p>
                    </div>
                  </div>
                </section>

                <section className={styles.proofWorkspace}>
                  <article className={`${styles.card} ${styles.proofPanelLarge}`}>
                    <div className={styles.proofSectionHeader}>
                      <div>
                        <span className={styles.cardLabelWarning}>Fix next</span>
                        <h2>Priority work from this scan</h2>
                      </div>
                      <span>{gapReport.priority_fixes.length} actions</span>
                    </div>
                    <div className={styles.proofFixList}>
                      {gapReport.priority_fixes.length ? (
                        gapReport.priority_fixes.slice(0, 5).map((fix) => (
                          <div key={`${fix.title}-${fix.score}`} className={styles.proofFixRow}>
                            <div className={styles.proofRowHeader}>
                              <strong>{fix.title}</strong>
                              <span className={`${styles.impactBadge} ${impactClass(fix.impact)}`}>
                                {fix.impact}
                              </span>
                            </div>
                            <p>{fix.why}</p>
                            <div className={styles.proofNextStep}>
                              <span>Next step</span>
                              <strong>{fix.next_step}</strong>
                            </div>
                          </div>
                        ))
                      ) : (
                        <p className={styles.proofEmptyState}>
                          No priority fixes were generated for this scan yet.
                        </p>
                      )}
                    </div>
                  </article>

                  <article className={`${styles.card} ${styles.proofPanelLarge}`}>
                    <div className={styles.proofSectionHeader}>
                      <div>
                        <span className={styles.cardLabelViolet}>Missed by AI</span>
                        <h2>Buyer questions where you were absent</h2>
                      </div>
                      <span>{missedQueries.length} misses</span>
                    </div>
                    <div className={styles.proofQueryList}>
                      {missedQueries.length ? (
                        missedQueries.slice(0, 8).map((item) => (
                          <div key={`${item.provider}-${item.group}-${item.question}`} className={styles.proofQueryRow}>
                            <div className={styles.proofQueryMeta}>
                              <span>{formatProvider(item.provider)}</span>
                              <span>{item.group}</span>
                              <span>{Math.round(item.priority_score)} priority</span>
                            </div>
                            <strong>{item.question}</strong>
                            <div className={styles.proofSourceLine}>
                              <span>AI cited instead</span>
                              <small>{compactDomainList(item.cited_sources)}</small>
                            </div>
                          </div>
                        ))
                      ) : (
                        <p className={styles.proofEmptyState}>
                          Every provider-question result mentioned {client?.name ?? "your brand"} in this scan.
                        </p>
                      )}
                    </div>
                  </article>

                  <aside className={`${styles.card} ${styles.proofPanelSide}`}>
                    <div className={styles.proofSectionHeader}>
                      <div>
                        <span className={styles.cardLabelTeal}>Proof sources</span>
                        <h2>Domains AI trusted instead</h2>
                      </div>
                    </div>
                    <div className={styles.proofSourceList}>
                      {gapReport.source_opportunities.length ? (
                        gapReport.source_opportunities.slice(0, 8).map((source) => (
                          <div key={source.domain} className={styles.proofSourceRow}>
                            <div>
                              <strong>{source.domain}</strong>
                              <small>
                                {source.providers.map(formatProvider).join(", ")}
                                {source.groups.length ? ` · ${source.groups.join(", ")}` : ""}
                              </small>
                            </div>
                            <span>{source.missed_query_count} misses</span>
                            {source.top_urls[0] && (
                              <a href={source.top_urls[0]} target="_blank" rel="noopener noreferrer">
                                Open source
                              </a>
                            )}
                          </div>
                        ))
                      ) : (
                        <p className={styles.proofEmptyState}>
                          No replacement source domains were found in the missed answers.
                        </p>
                      )}
                    </div>
                  </aside>
                </section>

                <section className={styles.proofLedgerGrid}>
                  <article className={`${styles.card} ${styles.proofPanelLarge}`}>
                    <div className={styles.proofSectionHeader}>
                      <div>
                        <span className={styles.cardLabel}>Citation ledger</span>
                        <h2>Sources captured from AI answers</h2>
                      </div>
                      <span>{citations.length} citations</span>
                    </div>
                    <div className={styles.citationList}>
                      {citations.length ? (
                        citations.slice(0, 12).map((citation) => (
                          <article
                            key={citation.id}
                            className={styles.citationCard}
                          >
                            <div className={styles.citationMeta}>
                              <span>{formatProvider(citation.provider)}{citation.group ? ` · ${citation.group}` : ""}</span>
                              <a
                                href={citation.citation_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className={styles.citationLink}
                              >
                                {citation.source_domain ?? citation.citation_title ?? "Open source"}
                              </a>
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
                  </article>

                  <aside className={`${styles.card} ${styles.proofPanelSide}`}>
                    <div className={styles.proofSectionHeader}>
                      <div>
                        <span className={styles.cardLabelTeal}>Raw exports</span>
                        <h2>Downloadable scan files</h2>
                      </div>
                    </div>
                    <p className={styles.proofPanelCopy}>
                      Use these only when you need the underlying CSV or audit artifacts. The readable gap report above is the primary workflow.
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
