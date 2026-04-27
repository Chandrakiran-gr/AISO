"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import styles from "./competitors.module.css";

export const dynamic = "force-dynamic";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type CompetitorMetric = {
  name: string;
  score: number;
  mention_count: number;
  is_you: boolean;
};

type ProviderMetric = {
  id: string;
  score: number;
  mention_count: number;
  total_questions: number;
};

type MetricsData = {
  client_id: string;
  client_name: string;
  scan_id: string;
  overall_score: number;
  total_questions: number;
  provider_metrics: ProviderMetric[];
  competitors: CompetitorMetric[];
};

const PROVIDERS = [
  { id: "openai", name: "ChatGPT", color: "#10a37f" },
  { id: "claude", name: "Claude", color: "#e8b68a" },
  { id: "perplexity", name: "Perplexity", color: "#1fb8cd" },
  { id: "gemini", name: "Gemini", color: "#4285f4" },
];

function scoreColor(s: number) {
  if (s >= 60) return "var(--accent-teal)";
  if (s >= 35) return "#f59e0b";
  return "#ef4444";
}

function medal(rank: number) {
  if (rank === 0) return "1";
  if (rank === 1) return "2";
  if (rank === 2) return "3";
  return `#${rank + 1}`;
}

export default function CompetitorsPage() {
  const [client, setClient] = useState<ClientData | null>(null);
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
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
            setLoading(false);
            setClient(null);
          }
          return;
        }

        const metricsRes = await fetch(`${API}/v1/clients/${firstClient.id}/metrics`, {
          cache: "no-store",
        });
        const metricData: MetricsData | null = metricsRes.ok ? await metricsRes.json() : null;

        if (active) {
          setClient(firstClient);
          setMetrics(metricData);
          setLoading(false);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Unable to load competitors");
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, []);

  const sorted = [...(metrics?.competitors ?? [])].sort((a, b) => b.score - a.score);
  const top3 = sorted.slice(0, 3);

  return (
    <div className={styles.main}>
      <div className={styles.topBar}>
        <div className={styles.topBarLeft}>
          <span className={styles.pageTitle}>Competitor Benchmarking</span>
          <span className={styles.pageSub}>
            {metrics
              ? `AI mention share vs ${Math.max(metrics.competitors.length - 1, 0)} competitors`
              : client
                ? `Waiting for completed scan metrics for ${client.name}`
                : "Create a business profile to compare competitors"}
          </span>
        </div>
        <Link href="/onboarding" className={styles.newScanBtn}>New scan</Link>
      </div>

      <div className={styles.content}>
        {loading && <div className={styles.leaderboardCard}>Loading competitor metrics...</div>}
        {error && <div className={styles.leaderboardCard}>{error}</div>}
        {!loading && !metrics && (
          <div className={styles.leaderboardCard}>
            Run a completed scan with competitor names to populate benchmarking.
          </div>
        )}

        {metrics && (
          <>
            <div className={styles.podiumRow}>
              {[top3[1], top3[0], top3[2]].map((c, i) => {
                if (!c) return null;
                const actualRank = sorted.indexOf(c);
                const isMid = i === 1;
                return (
                  <div
                    key={`${c.name}-${c.is_you}`}
                    className={`${styles.podiumCard} ${isMid ? styles.first : ""} ${c.is_you ? styles.you : ""}`}
                  >
                    {c.is_you && <span className={styles.youBadge}>You</span>}
                    <span className={styles.podiumMedal}>{medal(actualRank)}</span>
                    <span className={styles.podiumName}>{c.is_you ? metrics.client_name : c.name}</span>
                    <span className={styles.podiumScore} style={{ color: scoreColor(c.score) }}>
                      {Math.round(c.score)}
                    </span>
                    <span className={styles.podiumLabel}>{c.mention_count} mentions</span>
                  </div>
                );
              })}
            </div>

            <h2 className={styles.sectionTitle}>Full Rankings</h2>
            <div className={styles.leaderboardCard}>
              <div className={styles.leaderboardHeader}>
                <span>#</span>
                <span>Business</span>
                {PROVIDERS.map((p) => (
                  <span key={p.id} style={{ color: p.color, textAlign: "center" }}>{p.name}</span>
                ))}
                <span style={{ textAlign: "right" }}>Overall</span>
              </div>
              {sorted.map((c, i) => (
                <div
                  key={`${c.name}-${c.is_you}`}
                  className={`${styles.leaderboardRow} ${c.is_you ? styles.isYouRow : ""}`}
                >
                  <span className={`${styles.rank} ${i < 3 ? styles.top : ""}`}>
                    {i < 3 ? medal(i) : i + 1}
                  </span>
                  <span className={styles.competitorName}>
                    {c.is_you ? metrics.client_name : c.name}
                    {c.is_you && <span className={styles.youTag}>you</span>}
                  </span>
                  {PROVIDERS.map((p) => {
                    const providerMetric = metrics.provider_metrics.find((item) => item.id === p.id);
                    const providerShare = c.is_you && providerMetric
                      ? providerMetric.score
                      : metrics.total_questions
                        ? (c.mention_count / metrics.total_questions) * 100
                        : 0;
                    return (
                      <span key={p.id} className={styles.providerScore} style={{ color: scoreColor(providerShare) }}>
                        {Math.round(providerShare)}
                      </span>
                    );
                  })}
                  <span className={styles.totalScore} style={{ color: scoreColor(c.score) }}>
                    {Math.round(c.score)}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
