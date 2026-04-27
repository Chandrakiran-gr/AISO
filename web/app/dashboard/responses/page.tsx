"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
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
  storage_path: string;
  original_filename: string | null;
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

export default function ResponsesPage() {
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
              <div className={styles.actionList}>
                {citations.length ? (
                  citations.map((citation) => (
                    <a
                      key={citation.id}
                      className={styles.actionRow}
                      href={citation.citation_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <span>
                        {citation.provider}
                        {citation.group ? ` · ${citation.group}` : ""} · {citation.source_domain ?? citation.citation_url}
                      </span>
                      <strong>Open</strong>
                    </a>
                  ))
                ) : (
                  <p className={styles.heroSub}>
                    Citation rows are not available for this scan yet. Raw response artifacts are listed beside this panel.
                  </p>
                )}
              </div>
            </article>

            <article className={`${styles.card} ${styles.actionsCard}`}>
              <span className={styles.cardLabelTeal}>Raw artifacts</span>
              <div className={styles.actionList}>
                {scan.artifacts?.length ? (
                  scan.artifacts.map((artifact) => (
                    <div key={artifact.id} className={styles.actionRow}>
                      <span>{artifact.original_filename ?? artifact.storage_path}</span>
                      <strong>{artifact.artifact_type}</strong>
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
