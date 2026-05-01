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

export default function ResponsesPage() {
  const { data: session } = useSession();
  const rawArtifactsUnlocked = canAccessRawArtifacts(CURRENT_PLAN, session?.user?.email);
  const [client, setClient] = useState<ClientData | null>(null);
  const [scan, setScan] = useState<ScanData | null>(null);
  const [citations, setCitations] = useState<CitationData[]>([]);
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
        if (latestComplete) {
          const [detailRes, citationsRes] = await Promise.all([
            fetch(`${API}/v1/clients/${firstClient.id}/scans/${latestComplete.id}`, { cache: "no-store" }),
            fetch(`${API}/v1/clients/${firstClient.id}/scans/${latestComplete.id}/citations`, { cache: "no-store" }),
          ]);
          scanDetail = detailRes.ok ? await detailRes.json() : latestComplete;
          citationRows = citationsRes.ok ? await citationsRes.json() : [];
        }

        if (active) {
          setClient(firstClient);
          setScan(scanDetail);
          setCitations(citationRows);
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

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Responses & Proof</h1>
          <p className={styles.topCrumb}>
            {client ? `${client.name} · latest scan evidence` : "No business profile yet"}
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
          <section className={styles.lowerGrid}>
            <article className={`${styles.card} ${styles.trendCard}`}>
              <span className={styles.cardLabel}>Citations</span>
              <div className={styles.citationList}>
                {citations.length ? (
                  citations.map((citation) => (
                    <article
                      key={citation.id}
                      className={styles.citationCard}
                    >
                      <div className={styles.citationMeta}>
                        <span>{citation.provider}{citation.group ? ` · ${citation.group}` : ""}</span>
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

            <article className={`${styles.card} ${styles.actionsCard}`}>
              <span className={styles.cardLabelTeal}>Exports</span>
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
            </article>
          </section>
        )}
      </main>
    </div>
  );
}
