"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import styles from "./scans.module.css";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type ScanData = {
  id: string;
  status: "pending" | "running" | "complete" | "failed" | string;
  providers: string[] | null;
  groups: string[] | null;
  skipped_providers?: string[] | null;
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
};

const PROVIDERS = [
  { id: "openai", color: "#10a37f" },
  { id: "claude", color: "#e8b68a" },
  { id: "perplexity", color: "#1fb8cd" },
  { id: "gemini", color: "#4285f4" },
];

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function scoreColor(status: string): string {
  if (status === "complete") return "var(--accent-teal)";
  if (status === "failed") return "#ef4444";
  if (status === "running" || status === "pending") return "#f59e0b";
  return "var(--text-secondary)";
}

export default function ScansPage() {
  const [client, setClient] = useState<ClientData | null>(null);
  const [scans, setScans] = useState<ScanData[]>([]);
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
          if (active) {
            setClient(null);
            setScans([]);
            setLoading(false);
          }
          return;
        }

        const scansRes = await fetch(`${API}/v1/clients/${firstClient.id}/scans`, {
          cache: "no-store",
        });
        if (!scansRes.ok) throw new Error("Unable to load scan history");
        const data: ScanData[] = await scansRes.json();

        if (active) {
          setClient(firstClient);
          setScans(data);
          setLoading(false);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Unable to load scans");
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, []);

  const stats = useMemo(() => {
    const complete = scans.filter((scan) => scan.status === "complete").length;
    const failed = scans.filter((scan) => scan.status === "failed").length;
    const running = scans.filter((scan) => ["pending", "running"].includes(scan.status)).length;
    return [
      { label: "Total scans", value: String(scans.length) },
      { label: "Complete", value: String(complete) },
      { label: "Running", value: String(running) },
      { label: "Failed", value: String(failed) },
    ];
  }, [scans]);

  return (
    <div className={styles.main}>
      <div className={styles.topBar}>
        <div className={styles.topBarLeft}>
          <span className={styles.pageTitle}>Scan History</span>
          <span className={styles.pageSub}>
            {client ? `All AI visibility scans for ${client.name}` : "No business profile yet"}
          </span>
        </div>
        <Link href="/onboarding" className={styles.newScanBtn}>
          New scan
        </Link>
      </div>

      <div className={styles.content}>
        {error && <div className={styles.emptyState}>{error}</div>}

        <div className={styles.statsRow}>
          {stats.map((s) => (
            <div key={s.label} className={styles.statCard}>
              <span className={styles.statValue}>{s.value}</span>
              <span className={styles.statLabel}>{s.label}</span>
            </div>
          ))}
        </div>

        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>All scans</h2>
          <span className={styles.sectionHint}>
            {loading ? "Loading..." : `${scans.length} runs total`}
          </span>
        </div>

        {!loading && scans.length === 0 ? (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>Search</div>
            <p className={styles.emptyTitle}>No scans yet</p>
            <p className={styles.emptySub}>
              Run your first AI visibility scan to start tracking how often AI platforms mention your business.
            </p>
            <Link href="/onboarding" className={styles.newScanBtn}>
              Run first scan
            </Link>
          </div>
        ) : (
          <div className={styles.scanList}>
            {scans.map((scan) => (
              <Link
                key={scan.id}
                href={`/dashboard/scans/${scan.id}`}
                className={styles.scanRow}
                aria-label={`Scan from ${formatDate(scan.created_at)}, status ${scan.status}`}
              >
                <div className={styles.scanMeta}>
                  <span className={styles.scanDate}>{formatDate(scan.created_at)}</span>
                  <span className={styles.scanProviders}>
                    {(scan.providers ?? []).map((pid) => {
                      const p = PROVIDERS.find((x) => x.id === pid);
                      return p ? (
                        <span
                          key={pid}
                          className={styles.providerDot}
                          style={{ background: p.color }}
                          title={pid}
                        />
                      ) : null;
                    })}
                    {(scan.groups ?? []).length} groups · {(scan.providers ?? []).length} platforms
                  </span>
                </div>

                <span
                  className={styles.scanScore}
                  style={{ color: scoreColor(scan.status) }}
                >
                  {scan.status}
                </span>

                <span className={`${styles.scanDelta} ${styles.same}`}>
                  {scan.skipped_providers?.length
                    ? `${scan.skipped_providers.length} skipped`
                    : scan.completed_at
                      ? `Completed ${formatDate(scan.completed_at)}`
                      : "Awaiting result"}
                </span>

                <span className={`${styles.statusBadge} ${styles[scan.status as "complete" | "running" | "failed" | "pending"] ?? ""}`}>
                  {scan.status}
                </span>

                <span className={styles.viewBtn}>View</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
