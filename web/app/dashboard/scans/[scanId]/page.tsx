"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { CURRENT_PLAN, PRO_UPGRADE_HREF, canAccessRawArtifacts } from "@/lib/plan";
import {
  DashboardOverview,
  type ActionData,
  type GapReport,
  type MetricsData,
} from "../../DashboardOverview";
import styles from "../scans.module.css";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type ArtifactData = {
  id: string;
  artifact_type: string;
  file_format: string | null;
  storage_backend: string;
  storage_path: string;
  original_filename: string | null;
  size_bytes: number | null;
  sha256: string | null;
  created_at?: string | null;
};

type ScanDetail = {
  id: string;
  client_id: string;
  status: string;
  providers: string[] | null;
  groups: string[] | null;
  skipped_providers?: string[] | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  error?: string | null;
  artifacts: ArtifactData[];
};

type CustomCitation = {
  url?: string | null;
  title?: string | null;
  domain?: string | null;
  rank?: number | null;
  source_type?: string | null;
  owner_type?: string | null;
  action_role?: string | null;
};

type CustomProviderResult = {
  mentioned: boolean;
  answer_excerpt?: string | null;
  citations: CustomCitation[];
};

type CustomQuestionResult = {
  question: string;
  providers: Record<string, CustomProviderResult>;
};

type CustomQuestionsData = {
  scan_id: string;
  client_id: string;
  data_status: string;
  questions: CustomQuestionResult[];
};

function formatDate(value?: string | null): string {
  if (!value) return "Not set";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(value: number | null): string {
  if (!value) return "Unknown size";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatStatus(value: string): string {
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : "Unknown";
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

function artifactMeta(artifact: ArtifactData, scan: ScanDetail): string {
  const format = artifact.file_format?.toUpperCase() ?? "FILE";
  const generatedAt = artifact.created_at ?? scan.completed_at ?? scan.created_at;
  return `${format} • ${formatBytes(artifact.size_bytes)} • Generated ${formatDate(generatedAt)}`;
}

function providerLabel(provider: string): string {
  const labels: Record<string, string> = {
    openai: "ChatGPT",
    claude: "Claude",
    perplexity: "Perplexity",
    gemini: "Gemini",
  };
  return labels[provider] ?? provider;
}

function sourceLabel(citation: CustomCitation): string {
  return citation.title || citation.domain || citation.url || "Source";
}

export default function ScanDetailPage() {
  const params = useParams<{ scanId: string }>();
  const { data: session } = useSession();
  const scanId = params.scanId;
  const rawArtifactsUnlocked = canAccessRawArtifacts(CURRENT_PLAN, session?.user?.email);
  const [client, setClient] = useState<ClientData | null>(null);
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [customQuestions, setCustomQuestions] = useState<CustomQuestionsData | null>(null);
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
  const [gapReport, setGapReport] = useState<GapReport | null>(null);
  const [actions, setActions] = useState<ActionData[]>([]);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      setLoading(true);
      setError(null);
      setOverviewError(null);
      setScan(null);
      setCustomQuestions(null);
      setMetrics(null);
      setGapReport(null);
      setActions([]);

      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error("Unable to load clients");
        const clients: ClientData[] = await clientsRes.json();
        const firstClient = clients[0] ?? null;
        if (!firstClient) throw new Error("No business profile found");

        const scanRes = await fetch(`${API}/v1/clients/${firstClient.id}/scans/${scanId}`, {
          cache: "no-store",
        });
        if (!scanRes.ok) throw new Error("Unable to load scan detail");
        const scanDetail: ScanDetail = await scanRes.json();
        const encodedScanId = encodeURIComponent(scanId);
        const [customQuestionsRes, metricsRes, actionsRes, gapReportRes] = await Promise.all([
          fetch(
            `${API}/v1/clients/${firstClient.id}/scans/${scanId}/custom-questions`,
            { cache: "no-store" },
          ),
          fetch(`${API}/v1/clients/${firstClient.id}/metrics?scan_id=${encodedScanId}`, {
            cache: "no-store",
          }),
          fetch(`${API}/v1/clients/${firstClient.id}/actions?status=open&scan_id=${encodedScanId}`, {
            cache: "no-store",
          }),
          fetch(`${API}/v1/clients/${firstClient.id}/gap-report?scan_id=${encodedScanId}`, {
            cache: "no-store",
          }),
        ]);
        const customQuestionData: CustomQuestionsData | null = customQuestionsRes.ok
          ? await customQuestionsRes.json()
          : null;
        const metricsData: MetricsData | null = metricsRes.ok ? await metricsRes.json() : null;
        const actionsData: ActionData[] = actionsRes.ok ? await actionsRes.json() : [];
        const gapReportData: GapReport | null = gapReportRes.ok ? await gapReportRes.json() : null;
        const overviewLoadFailed = [metricsRes, actionsRes, gapReportRes].some(
          (response) => !response.ok && response.status !== 404,
        );

        if (active) {
          setClient(firstClient);
          setScan(scanDetail);
          setCustomQuestions(customQuestionData);
          setMetrics(metricsData);
          setActions(actionsData);
          setGapReport(gapReportData);
          setOverviewError(overviewLoadFailed ? "Some scan overview data could not be loaded." : null);
          setLoading(false);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Unable to load scan detail");
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [scanId]);

  return (
    <div className={styles.main}>
      <div className={styles.topBar}>
        <div className={styles.topBarLeft}>
          <span className={styles.pageTitle}>Scan Detail</span>
          <span className={styles.pageSub}>
            {client && scan
              ? `${client.name} · ${formatStatus(scan.status)} ${formatDate(scan.completed_at ?? scan.created_at)}`
              : client?.name ?? "Loading scan"}
          </span>
        </div>
        <Link href="/dashboard/scans" className={styles.newScanBtn}>
          Back to scans
        </Link>
      </div>

      <div className={`${styles.content} ${styles.detailContent}`}>
        {loading && <div className={styles.emptyState}>Loading scan detail...</div>}
        {error && <div className={styles.emptyState}>{error}</div>}

        {scan && (
          <>
            <div className={styles.statsRow}>
              <div className={styles.statCard}>
                <span className={styles.statValue}>{formatStatus(scan.status)}</span>
                <span className={styles.statLabel}>Status</span>
              </div>
              <div className={styles.statCard}>
                <span className={styles.statValue}>{scan.providers?.length ?? 0}</span>
                <span className={styles.statLabel}>Providers</span>
              </div>
              <div className={styles.statCard}>
                <span className={styles.statValue}>{scan.groups?.length ?? 0}</span>
                <span className={styles.statLabel}>Intent groups</span>
              </div>
              <div className={styles.statCard}>
                <span className={styles.statValue}>{scan.artifacts.length}</span>
                <span className={styles.statLabel}>Exports</span>
              </div>
            </div>

            <section className={styles.overviewSection} aria-labelledby="scan-overview-heading">
              <div className={styles.sectionHeader}>
                <div>
                  <h2 id="scan-overview-heading" className={styles.sectionTitle}>Overview</h2>
                  <span className={styles.sectionHint}>Metrics, intent gaps, and recommended actions for this scan</span>
                </div>
              </div>
              {overviewError && <div className={styles.overviewNotice}>{overviewError}</div>}
              <DashboardOverview
                clientName={client?.name}
                metrics={metrics}
                gapReport={gapReport}
                actions={actions}
                actionScopeLabel="this scan"
                metricScopeLabel="this scan"
                scanMetaLabel={`Selected scan: ${formatStatus(scan.status)}${
                  scan.providers?.length ? ` · ${scan.providers.length} platforms` : ""
                }`}
              />
            </section>

            {scan.error && (
              <div className={styles.detailCard}>
                <h2 className={styles.sectionTitle}>Error</h2>
                <p className={styles.emptySub}>{scan.error}</p>
              </div>
            )}

            {!!scan.skipped_providers?.length && (
              <div className={styles.detailCard}>
                <h2 className={styles.sectionTitle}>Skipped providers</h2>
                <p className={styles.emptySub}>{scan.skipped_providers.join(", ")}</p>
              </div>
            )}

            <div className={styles.detailGrid}>
              <div className={styles.detailCard}>
                <h2 className={styles.sectionTitle}>Timing</h2>
                <p className={styles.detailRow}>Created <strong>{formatDate(scan.created_at)}</strong></p>
                <p className={styles.detailRow}>Started <strong>{formatDate(scan.started_at)}</strong></p>
                <p className={styles.detailRow}>Completed <strong>{formatDate(scan.completed_at)}</strong></p>
              </div>

              <div className={styles.detailCard}>
                <h2 className={styles.sectionTitle}>Configuration</h2>
                <p className={styles.detailRow}>Providers <strong>{scan.providers?.join(", ") || "None"}</strong></p>
                <p className={styles.detailRow}>Groups <strong>{scan.groups?.join(", ") || "None"}</strong></p>
              </div>
            </div>

            {!!customQuestions?.questions.length && (
              <div className={`${styles.detailCard} ${styles.customQuestionsCard}`}>
                <div className={styles.exportsHeader}>
                  <div>
                    <h2 className={styles.sectionTitle}>Custom Questions</h2>
                    <p className={styles.exportsSub}>
                      These were client-authored questions added only for this scan. They do not affect benchmark scores.
                    </p>
                  </div>
                  <span className={styles.exportsPlanBadge}>
                    {customQuestions.questions.length} question{customQuestions.questions.length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className={styles.customQuestionList}>
                  {customQuestions.questions.map((item) => (
                    <article key={item.question} className={styles.customQuestionItem}>
                      <h3>{item.question}</h3>
                      <div className={styles.customProviderGrid}>
                        {Object.entries(item.providers).map(([provider, result]) => (
                          <details key={provider} className={styles.customProviderCard}>
                            <summary>
                              <span>{providerLabel(provider)}</span>
                              <strong className={result.mentioned ? styles.mentioned : styles.notMentioned}>
                                {result.mentioned ? "Mentioned" : "Not mentioned"}
                              </strong>
                            </summary>
                            {result.answer_excerpt && (
                              <p className={styles.customAnswer}>{result.answer_excerpt}</p>
                            )}
                            {result.citations.length > 0 ? (
                              <ul className={styles.customCitationList}>
                                {result.citations.map((citation, index) => (
                                  <li key={`${citation.url ?? citation.domain ?? "source"}-${index}`}>
                                    {citation.url ? (
                                      <a href={citation.url} target="_blank" rel="noreferrer">
                                        {sourceLabel(citation)}
                                      </a>
                                    ) : (
                                      <span>{sourceLabel(citation)}</span>
                                    )}
                                    {citation.source_type && <small>{citation.source_type.replaceAll("_", " ")}</small>}
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <p className={styles.customNoEvidence}>No citations were captured for this provider answer.</p>
                            )}
                          </details>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            )}

            <div className={`${styles.detailCard} ${styles.exportsCard}`}>
              <div className={styles.exportsHeader}>
                <div>
                  <h2 className={styles.sectionTitle}>Exports</h2>
                  <p className={styles.exportsSub}>
                    {rawArtifactsUnlocked
                      ? "Downloadable scan files are available for this account."
                      : "Downloadable scan files are available with Pro."}
                  </p>
                </div>
                {!rawArtifactsUnlocked && (
                  <span className={styles.exportsPlanBadge}>Pro feature</span>
                )}
              </div>
              {scan.artifacts.length ? (
                <div className={styles.scanList}>
                  {scan.artifacts.map((artifact) => (
                    <div
                      key={artifact.id}
                      className={`${styles.artifactRow} ${rawArtifactsUnlocked ? "" : styles.artifactLocked}`}
                    >
                      <div className={styles.artifactInfo}>
                        <span className={styles.artifactIcon}>
                          {(artifact.file_format ?? "file").slice(0, 3).toUpperCase()}
                        </span>
                        <span className={styles.artifactText}>
                          <span className={styles.scanDate}>{artifactTitle(artifact)}</span>
                          <span className={styles.scanProviders}>
                            {artifactMeta(artifact, scan)}
                          </span>
                        </span>
                      </div>
                      {rawArtifactsUnlocked ? (
                        <a
                          href={`${API}/v1/clients/${client?.id ?? scan.client_id}/scans/${scan.id}/artifacts/${artifact.id}/download`}
                          className={styles.artifactReadyBadge}
                        >
                          Download
                        </a>
                      ) : (
                        <div className={styles.artifactLockAction}>
                          <Link href={PRO_UPGRADE_HREF} className={styles.artifactUpgradeBtn}>
                            Get it
                          </Link>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className={styles.emptySub}>No exports have been saved for this scan yet.</p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
