"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
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

export default function ScanDetailPage() {
  const params = useParams<{ scanId: string }>();
  const scanId = params.scanId;
  const [client, setClient] = useState<ClientData | null>(null);
  const [scan, setScan] = useState<ScanDetail | null>(null);
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
        if (!firstClient) throw new Error("No business profile found");

        const scanRes = await fetch(`${API}/v1/clients/${firstClient.id}/scans/${scanId}`, {
          cache: "no-store",
        });
        if (!scanRes.ok) throw new Error("Unable to load scan detail");
        const scanDetail: ScanDetail = await scanRes.json();

        if (active) {
          setClient(firstClient);
          setScan(scanDetail);
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
            {client ? `${client.name} · ${scanId}` : scanId}
          </span>
        </div>
        <Link href="/dashboard/scans" className={styles.newScanBtn}>
          Back to scans
        </Link>
      </div>

      <div className={styles.content}>
        {loading && <div className={styles.emptyState}>Loading scan detail...</div>}
        {error && <div className={styles.emptyState}>{error}</div>}

        {scan && (
          <>
            <div className={styles.statsRow}>
              <div className={styles.statCard}>
                <span className={styles.statValue}>{scan.status}</span>
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
                <span className={styles.statLabel}>Artifacts</span>
              </div>
            </div>

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

            <div className={styles.detailCard}>
              <h2 className={styles.sectionTitle}>Artifacts</h2>
              {scan.artifacts.length ? (
                <div className={styles.scanList}>
                  {scan.artifacts.map((artifact) => (
                    <div key={artifact.id} className={styles.artifactRow}>
                      <div className={styles.scanMeta}>
                        <span className={styles.scanDate}>
                          {artifact.original_filename ?? artifact.storage_path}
                        </span>
                        <span className={styles.scanProviders}>
                          {artifact.artifact_type} · {artifact.file_format ?? "file"} · {formatBytes(artifact.size_bytes)}
                        </span>
                      </div>
                      <code className={styles.artifactPath}>{artifact.storage_path}</code>
                    </div>
                  ))}
                </div>
              ) : (
                <p className={styles.emptySub}>No raw scan artifacts have been saved for this scan yet.</p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
