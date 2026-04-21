"use client";

import Link from "next/link";
import { useState, useEffect, useRef } from "react";
import styles from "./dashboard.module.css";

// ── Mock data (Phase 4 will replace with real API) ────────────────────────────
const MOCK_SCORE = 42;
const MOCK_DELTA = +6;

const MOCK_PROVIDERS = [
  { id: "openai",     name: "ChatGPT",    color: "#10a37f", score: 51, mentions: 38, total: 100 },
  { id: "claude",     name: "Claude",     color: "#e8b68a", score: 44, mentions: 31, total: 100 },
  { id: "perplexity", name: "Perplexity", color: "#1fb8cd", score: 39, mentions: 28, total: 100 },
  { id: "gemini",     name: "Gemini",     color: "#4285f4", score: 34, mentions: 24, total: 100 },
];

const MOCK_GROUPS = [
  { id: "G1", label: "Awareness",   score: 58 },
  { id: "G2", label: "Comparison",  score: 47 },
  { id: "G3", label: "Transact",    score: 39 },
  { id: "G4", label: "Local",       score: 61 },
  { id: "G5", label: "Technical",   score: 33 },
  { id: "G6", label: "Trust",       score: 29 },
  { id: "G7", label: "Support",     score: 22 },
];

const MOCK_COMPETITORS = [
  { name: "Competitor A",   score: 71, isYou: false },
  { name: "Competitor B",   score: 58, isYou: false },
  { name: "Your Business",  score: 42, isYou: true  },
  { name: "Competitor C",   score: 35, isYou: false },
  { name: "Competitor D",   score: 28, isYou: false },
];

const MOCK_ACTIONS = [
  {
    priority: "high",
    title: "Add entity disambiguation to your homepage",
    sub: "G6 Trust · ChatGPT mentions you ambiguously — add Schema.org LocalBusiness markup",
  },
  {
    priority: "high",
    title: "Publish a direct answer to 'who is the best [your category]?'",
    sub: "G2 Comparison · You're absent from 94% of comparison queries on Claude",
  },
  {
    priority: "medium",
    title: "Get listed on 3 more authoritative directories",
    sub: "G1 Awareness · Citations drive AI mention frequency — Yelp, BBB, G2 are top sources",
  },
  {
    priority: "medium",
    title: "Create a FAQ page targeting G5 technical questions",
    sub: "G5 Technical · Scoring 33 — answer-first content significantly improves AI citation",
  },
  {
    priority: "low",
    title: "Add customer review schema (AggregateRating)",
    sub: "G6 Trust · Structured review data increases trust-query citations by ~18%",
  },
];

const NAV = [
  { icon: "📊", label: "Overview",         href: "/dashboard",          active: true  },
  { icon: "🔍", label: "Scan History",     href: "/dashboard/scans",    active: false },
  { icon: "🏆", label: "Competitors",      href: "/dashboard/competitors", active: false },
  { icon: "⚡", label: "Action Plan",      href: "/dashboard/actions",  active: false },
  { icon: "⚙️", label: "Settings",         href: "/dashboard/settings", active: false },
];

// ── Score ring component ───────────────────────────────────────────────────────
function ScoreRing({ score, delta }: { score: number; delta: number }) {
  const [displayed, setDisplayed] = useState(0);
  const radius = 65;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (displayed / 100) * circumference;

  useEffect(() => {
    const timer = setTimeout(() => setDisplayed(score), 200);
    return () => clearTimeout(timer);
  }, [score]);

  const color = score >= 60 ? "#00d4aa" : score >= 35 ? "#f59e0b" : "#ef4444";

  return (
    <div className={styles.scoreCard}>
      <div className={styles.scoreRingWrap}>
        <svg className={styles.scoreRingSvg} viewBox="0 0 160 160">
          <defs>
            <linearGradient id="ringGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%"   stopColor="#00d4aa" />
              <stop offset="100%" stopColor="#7c3aed" />
            </linearGradient>
          </defs>
          <circle className={styles.scoreRingBg} cx="80" cy="80" r={radius} />
          <circle
            className={styles.scoreRingFill}
            cx="80" cy="80" r={radius}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ stroke: color }}
          />
        </svg>
        <div className={styles.scoreCenter}>
          <span className={styles.scoreNumber} style={{ color }}>{displayed}</span>
          <span className={styles.scoreLabel}>/ 100</span>
        </div>
      </div>

      <div className={styles.scoreMeta}>
        <p className={styles.scoreTitle}>AI Visibility Score</p>
        <p className={styles.scoreSubtext}>Based on 100 questions · 4 platforms</p>
      </div>

      <span className={`${styles.scoreDelta} ${delta >= 0 ? styles.up : styles.down}`}>
        {delta >= 0 ? "↑" : "↓"} {Math.abs(delta)} pts vs last scan
      </span>
    </div>
  );
}

// ── Provider card ─────────────────────────────────────────────────────────────
function ProviderCard({ name, color, score, mentions, total }: {
  name: string; color: string; score: number; mentions: number; total: number;
}) {
  const [width, setWidth] = useState(0);
  useEffect(() => { setTimeout(() => setWidth(score), 300); }, [score]);

  return (
    <div className={styles.providerCard}>
      <div className={styles.providerHeader}>
        <div className={styles.providerName}>
          <span className={styles.providerDot} style={{ background: color }} />
          {name}
        </div>
      </div>
      <div className={styles.providerScore} style={{ color }}>{score}</div>
      <div className={styles.providerBar}>
        <div className={styles.providerBarFill} style={{ width: `${width}%`, background: color }} />
      </div>
      <div className={styles.providerMeta}>{mentions}/{total} questions mentioned you</div>
    </div>
  );
}

// ── Intent group chart ────────────────────────────────────────────────────────
function GroupChart() {
  const [widths, setWidths] = useState<number[]>(MOCK_GROUPS.map(() => 0));
  useEffect(() => {
    const t = setTimeout(() => setWidths(MOCK_GROUPS.map((g) => g.score)), 300);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <h2 className={styles.cardTitle}>Intent Group Breakdown</h2>
        <span className={styles.cardBadge}>7 groups</span>
      </div>
      <div className={styles.groupList}>
        {MOCK_GROUPS.map((g, i) => (
          <div key={g.id} className={styles.groupRow}>
            <span className={styles.groupLabel}>{g.id} · {g.label}</span>
            <div className={styles.groupBar}>
              <div className={styles.groupBarFill} style={{ width: `${widths[i]}%` }} />
            </div>
            <span className={styles.groupScore}>{g.score}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Competitor leaderboard ─────────────────────────────────────────────────────
function CompetitorBoard() {
  const sorted = [...MOCK_COMPETITORS].sort((a, b) => b.score - a.score);
  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <h2 className={styles.cardTitle}>Competitor Leaderboard</h2>
        <span className={styles.cardBadge}>AI mentions ranking</span>
      </div>
      <div className={styles.competitorList}>
        {sorted.map((c, i) => (
          <div key={c.name} className={styles.competitorRow}>
            <span className={styles.competitorRank}>#{i + 1}</span>
            <span className={`${styles.competitorName} ${c.isYou ? styles.isYou : ""}`}>
              {c.name}
              {c.isYou && <span className={styles.youBadge} style={{ marginLeft: 6 }}>you</span>}
            </span>
            <span className={styles.competitorScore}>{c.score}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Action items ──────────────────────────────────────────────────────────────
function ActionItems() {
  return (
    <div className={styles.card} style={{ gridColumn: "1 / -1" }}>
      <div className={styles.cardHeader}>
        <h2 className={styles.cardTitle}>Priority Action Plan</h2>
        <span className={styles.cardBadge}>{MOCK_ACTIONS.length} items</span>
      </div>
      <div className={styles.actionList}>
        {MOCK_ACTIONS.map((a, i) => (
          <div key={i} className={styles.actionItem}>
            <div className={`${styles.actionPriority} ${styles[a.priority]}`}>
              {a.priority === "high" ? "!" : a.priority === "medium" ? "~" : "·"}
            </div>
            <div className={styles.actionContent}>
              <p className={styles.actionTitle}>{a.title}</p>
              <p className={styles.actionSub}>{a.sub}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const [scanRunning] = useState(false);

  return (
    <div className={styles.shell}>
      {/* Sidebar */}
      <aside className={styles.sidebar} aria-label="Dashboard navigation">
        <Link href="/" className={styles.sidebarLogo}>
          <span className={styles.logoMark}>◆</span>
          <span className="gradient-text">AISO</span>
        </Link>

        <div className={styles.sidebarSection}>
          <span className={styles.sidebarLabel}>Workspace</span>
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`${styles.navItem} ${item.active ? styles.active : ""}`}
            >
              <span className={styles.navIcon}>{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </div>

        <div className={styles.sidebarSpacer} />

        <div className={styles.sidebarFooter}>
          <span className={styles.userEmail}>chandrakiran.gr25@gmail.com</span>
          <button className={styles.signOutBtn}>Sign out</button>
        </div>
      </aside>

      {/* Main */}
      <main className={styles.main}>
        {/* Top bar */}
        <div className={styles.topBar}>
          <div className={styles.topBarLeft}>
            <span className={styles.pageTitle}>Overview</span>
            <span className={styles.pageSub}>Last scan: Today at 9:42 AM · 100 questions</span>
          </div>
          <div className={styles.topBarRight}>
            <Link href="/onboarding" className={styles.newScanBtn}>
              ▶ New scan
            </Link>
          </div>
        </div>

        {/* Content */}
        <section className={styles.content}>
          {/* Scan running banner */}
          {scanRunning && (
            <div className={styles.scanBanner}>
              <div className={styles.scanBannerSpinner} />
              <p className={styles.scanBannerText}>
                <strong>Scan in progress</strong> — querying 4 AI platforms across 100 questions. ~6 min remaining.
              </p>
            </div>
          )}

          {/* Score ring + provider cards */}
          <div className={styles.heroRow}>
            <ScoreRing score={MOCK_SCORE} delta={MOCK_DELTA} />
            <div className={styles.providerGrid}>
              {MOCK_PROVIDERS.map((p) => (
                <ProviderCard key={p.id} {...p} />
              ))}
            </div>
          </div>

          {/* Group breakdown + competitor leaderboard */}
          <div className={styles.sectionRow}>
            <GroupChart />
            <CompetitorBoard />
          </div>

          {/* Action items — full width */}
          <div className={styles.sectionRow}>
            <ActionItems />
          </div>
        </section>
      </main>
    </div>
  );
}
