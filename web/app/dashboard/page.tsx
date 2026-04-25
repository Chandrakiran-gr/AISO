"use client";

import type { CSSProperties } from "react";
import Link from "next/link";
import { useEffect, useState } from "react";
import styles from "./dashboard.module.css";

export const dynamic = "force-dynamic";

const API = "/api/proxy";

interface ScanData {
  id: string;
  status: string;
  providers: string[];
  created_at: string;
}

interface ClientData {
  id: string;
  name: string;
}

const PROVIDERS = [
  { id: "openai", name: "ChatGPT", color: "#10a37f", score: 72, delta: "+5" },
  { id: "claude", name: "Claude", color: "#d4a27f", score: 58, delta: "+2" },
  { id: "perplexity", name: "Perplexity", color: "#1fb8cd", score: 81, delta: "-1" },
  { id: "gemini", name: "Gemini", color: "#4285f4", score: 54, delta: "+12" },
];

const COMPETITORS = [
  { name: "Dunkin'", score: 78, color: "#ffd93d" },
  { name: "You", score: 67, color: "#00d4aa", gradient: true },
  { name: "Blue Btl", score: 52, color: "#1fb8cd" },
  { name: "Tatte", score: 41, color: "#d4a27f" },
];

const ACTIONS = [
  { title: "Add JSON-LD schema to homepage", impact: "+4-6" },
  { title: "Verify Google Business Profile", impact: "+3-5" },
];

const TREND_POINTS = "16,88 94,68 172,78 250,58 328,54 406,64 484,54";

function providerStyle(color: string, score: number): CSSProperties {
  return {
    "--provider-color": color,
    "--provider-score": `${score}%`,
  } as CSSProperties;
}

function ScoreRing({ score }: { score: number }) {
  const radius = 64;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;

  return (
    <div className={styles.scoreRingWrap} aria-label={`AI visibility score ${score} out of 100`}>
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
        <span className={styles.scoreNumber}>{score}</span>
        <span className={styles.scoreDenominator}>/100</span>
      </div>
    </div>
  );
}

function ProviderCard({ provider, selected = false }: {
  provider: (typeof PROVIDERS)[number];
  selected?: boolean;
}) {
  return (
    <article
      className={`${styles.providerCard} ${selected ? styles.providerCardSelected : ""}`}
      style={providerStyle(provider.color, provider.score)}
    >
      <div className={styles.providerHeader}>
        <span className={styles.providerDot} />
        <span className={styles.providerName}>{provider.name}</span>
      </div>
      <div className={styles.providerMetric}>
        <span className={styles.providerScore}>{provider.score}</span>
        <span className={styles.providerOutOf}>/100</span>
        <span className={provider.delta.startsWith("-") ? styles.providerDeltaDown : styles.providerDelta}>
          {provider.delta}
        </span>
      </div>
      <span className={styles.providerTrack}>
        <span className={styles.providerFill} />
      </span>
    </article>
  );
}

function CompetitorRow({ competitor }: { competitor: (typeof COMPETITORS)[number] }) {
  return (
    <div className={styles.competitorRow}>
      <span className={styles.competitorName}>{competitor.name}</span>
      <span className={styles.competitorTrack}>
        <span
          className={`${styles.competitorFill} ${competitor.gradient ? styles.gradientFill : ""}`}
          style={{
            "--competitor-color": competitor.color,
            "--competitor-score": `${competitor.score}%`,
          } as CSSProperties}
        />
      </span>
      <span className={styles.competitorScore}>{competitor.score}</span>
    </div>
  );
}

export default function DashboardPage() {
  const [latestScan, setLatestScan] = useState<ScanData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`);
        if (!clientsRes.ok) return;
        const clients: ClientData[] = await clientsRes.json();
        if (!clients.length) return;

        const scansRes = await fetch(`${API}/api/v1/clients/${clients[0].id}/scans`);
        if (!scansRes.ok) return;

        const scans: ScanData[] = await scansRes.json();
        if (scans.length) setLatestScan(scans[0]);
      } catch {
        // API offline or no local data yet: keep the prototype-quality dashboard visible.
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  const scanRunning = latestScan?.status === "running" || latestScan?.status === "pending";
  const lastScanLabel = latestScan
    ? new Date(latestScan.created_at).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Apr 25";

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Dashboard</h1>
          <p className={styles.topCrumb}>Overview</p>
        </div>
        <div className={styles.topActions}>
          <button type="button" className={styles.headerPill}>⌘K Search</button>
          <button type="button" className={styles.headerPill}>Alerts</button>
          <span className={styles.avatar}>CK</span>
        </div>
      </header>

      <main className={styles.content}>
        <section className={styles.hero}>
          <div>
            <h2 className={styles.heroTitle}>What AI is saying about Boston Brew</h2>
            <p className={styles.heroSub}>
              Visibility improved, but Dunkin&apos; still owns transactional and family-fit queries.
            </p>
          </div>
          <Link href="/onboarding" className={styles.newScanBtn}>Run new scan</Link>
        </section>

        {scanRunning && (
          <div className={styles.scanBanner}>
            <span className={styles.scanBannerSpinner} aria-hidden="true" />
            <p>
              <strong>Scan in progress</strong> — querying AI platforms across the selected question set.
            </p>
          </div>
        )}

        {!loading && !latestScan && (
          <div className={styles.previewBanner}>
            Showing prototype-quality sample metrics until your first completed scan is available.
          </div>
        )}

        <section className={styles.summaryGrid}>
          <article className={`${styles.card} ${styles.scoreCard}`}>
            <span className={styles.cardLabelTeal}>Overall score</span>
            <ScoreRing score={67} />
            <p className={styles.scoreCaption}>AI Visibility Score</p>
            <Link href="/dashboard/responses" className={styles.secondaryButton}>View proof</Link>
          </article>

          <article className={`${styles.card} ${styles.urgencyCard}`}>
            <span className={styles.cardLabelWarning}>Urgency</span>
            <strong className={styles.gapMetric}>-11 pts</strong>
            <p className={styles.gapCopy}>behind Dunkin&apos; across all AI providers</p>
            <div className={styles.cardDivider} />
            <span className={styles.smallMuted}>Next best move</span>
            <div className={styles.nextMoveRow}>
              <strong>Fix entity schema first</strong>
              <Link href="/onboarding" className={styles.primaryButton}>Run scan</Link>
            </div>
          </article>

          <article className={`${styles.card} ${styles.competitorCard}`}>
            <span className={styles.cardLabelViolet}>Top competitors</span>
            <div className={styles.competitorList}>
              {COMPETITORS.map((competitor) => (
                <CompetitorRow key={competitor.name} competitor={competitor} />
              ))}
            </div>
            <Link href="/dashboard/competitors" className={styles.secondaryButton}>View comparison</Link>
          </article>
        </section>

        <section aria-labelledby="providers-heading">
          <h2 id="providers-heading" className={styles.sectionLabel}>Provider breakdown</h2>
          <div className={styles.providerGrid}>
            {PROVIDERS.map((provider, index) => (
              <ProviderCard key={provider.id} provider={provider} selected={index === 0} />
            ))}
          </div>
        </section>

        <section className={styles.lowerGrid}>
          <article className={`${styles.card} ${styles.trendCard}`}>
            <span className={styles.cardLabel}>Visibility trend / 30 days</span>
            <svg className={styles.trendChart} viewBox="0 0 520 132" role="img" aria-label="Visibility trend from March 20 to April 25">
              <line x1="16" y1="34" x2="504" y2="34" />
              <line x1="16" y1="68" x2="504" y2="68" />
              <line x1="16" y1="102" x2="504" y2="102" />
              <polyline points={TREND_POINTS} />
              {[16, 94, 172, 250, 328, 406, 484].map((x, index) => (
                <circle key={x} cx={x} cy={[88, 68, 78, 58, 54, 64, 54][index]} r="3" />
              ))}
            </svg>
            <div className={styles.chartLabels}>
              <span>Mar 20</span>
              <span>Apr 25</span>
            </div>
          </article>

          <article className={`${styles.card} ${styles.actionsCard}`}>
            <span className={styles.cardLabelTeal}>Priority actions</span>
            <p className={styles.actionSummary}>12 open actions could add +15-20 pts</p>
            <div className={styles.actionList}>
              {ACTIONS.map((action) => (
                <div key={action.title} className={styles.actionRow}>
                  <span className={styles.actionDot} />
                  <span>{action.title}</span>
                  <strong>{action.impact}</strong>
                </div>
              ))}
            </div>
            <Link href="/dashboard/actions" className={styles.primaryButton}>Open actions</Link>
          </article>
        </section>

        <p className={styles.scanMeta}>
          Last scan: {lastScanLabel}
          {latestScan?.providers?.length ? ` · ${latestScan.providers.length} platforms` : ""}
        </p>
      </main>
    </div>
  );
}
