"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import styles from "./competitors.module.css";

export const dynamic = "force-dynamic";

const PROVIDERS = [
  { id: "openai",     name: "ChatGPT",    color: "#10a37f" },
  { id: "claude",     name: "Claude",     color: "#e8b68a" },
  { id: "perplexity", name: "Perplexity", color: "#1fb8cd" },
  { id: "gemini",     name: "Gemini",     color: "#4285f4" },
];

// ── Mock competitor data (replaced by real ScanResult rows in Phase 5) ─────────
const COMPETITORS = [
  {
    name: "Your Business",
    isYou: true,
    total: 42,
    scores: { openai: 51, claude: 44, perplexity: 39, gemini: 34 },
  },
  {
    name: "Competitor A",
    isYou: false,
    total: 71,
    scores: { openai: 78, claude: 69, perplexity: 65, gemini: 72 },
  },
  {
    name: "Competitor B",
    isYou: false,
    total: 58,
    scores: { openai: 61, claude: 55, perplexity: 53, gemini: 63 },
  },
  {
    name: "Competitor C",
    isYou: false,
    total: 35,
    scores: { openai: 38, claude: 32, perplexity: 29, gemini: 41 },
  },
  {
    name: "Competitor D",
    isYou: false,
    total: 28,
    scores: { openai: 30, claude: 25, perplexity: 24, gemini: 33 },
  },
];

function scoreColor(s: number) {
  if (s >= 60) return "var(--accent-teal)";
  if (s >= 35) return "#f59e0b";
  return "#ef4444";
}

function medal(rank: number) {
  if (rank === 0) return "🥇";
  if (rank === 1) return "🥈";
  if (rank === 2) return "🥉";
  return `#${rank + 1}`;
}

// Sort descending by total score
const SORTED = [...COMPETITORS].sort((a, b) => b.total - a.total);
const TOP3   = SORTED.slice(0, 3);

export default function CompetitorsPage() {
  const [barWidths, setBarWidths] = useState<Record<string, number>>({});

  useEffect(() => {
    const widths: Record<string, number> = {};
    SORTED.forEach((c) => {
      PROVIDERS.forEach((p) => {
        widths[`${c.name}-${p.id}`] = (c.scores as Record<string, number>)[p.id] ?? 0;
      });
    });
    const t = setTimeout(() => setBarWidths(widths), 300);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className={styles.main}>
      <div className={styles.topBar}>
        <div className={styles.topBarLeft}>
          <span className={styles.pageTitle}>Competitor Benchmarking</span>
          <span className={styles.pageSub}>AI mention share vs {COMPETITORS.length - 1} competitors across 4 platforms</span>
        </div>
        <Link href="/onboarding" className={styles.newScanBtn}>▶ New scan</Link>
      </div>

      <div className={styles.content}>
        <div className={styles.podiumRow}>
          {[TOP3[1], TOP3[0], TOP3[2]].map((c, i) => {
            if (!c) return null;
            const actualRank = SORTED.indexOf(c);
            const isMid = i === 1;
            return (
              <div
                key={c.name}
                className={`${styles.podiumCard} ${isMid ? styles.first : ""} ${c.isYou ? styles.you : ""}`}
              >
                {c.isYou && <span className={styles.youBadge}>You</span>}
                <span className={styles.podiumMedal}>{medal(actualRank)}</span>
                <span className={styles.podiumName}>{c.name}</span>
                <span className={styles.podiumScore} style={{ color: scoreColor(c.total) }}>
                  {c.total}
                </span>
                <span className={styles.podiumLabel}>AI visibility score</span>
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
          {SORTED.map((c, i) => (
            <div
              key={c.name}
              className={`${styles.leaderboardRow} ${c.isYou ? styles.isYouRow : ""}`}
            >
              <span className={`${styles.rank} ${i < 3 ? styles.top : ""}`}>
                {i < 3 ? medal(i) : i + 1}
              </span>
              <span className={styles.competitorName}>
                {c.name}
                {c.isYou && <span className={styles.youTag}>you</span>}
              </span>
              {PROVIDERS.map((p) => {
                const s = (c.scores as Record<string, number>)[p.id] ?? 0;
                return (
                  <span key={p.id} className={styles.providerScore} style={{ color: scoreColor(s) }}>
                    {s}
                  </span>
                );
              })}
              <span className={styles.totalScore} style={{ color: scoreColor(c.total) }}>
                {c.total}
              </span>
            </div>
          ))}
        </div>

        <h2 className={styles.sectionTitle}>Per-Platform Breakdown</h2>
        <div className={styles.providerRow}>
          {PROVIDERS.map((p) => (
            <div key={p.id} className={styles.providerBreakCard}>
              <div className={styles.providerBreakHeader}>
                <span className={styles.providerDot} style={{ background: p.color }} />
                <span className={styles.providerBreakName}>{p.name}</span>
              </div>
              {SORTED.map((c) => {
                const s = (c.scores as Record<string, number>)[p.id] ?? 0;
                const w = barWidths[`${c.name}-${p.id}`] ?? 0;
                return (
                  <div key={c.name} className={styles.breakRow}>
                    <span className={styles.breakName} title={c.name}>
                      {c.isYou ? "You" : c.name.replace("Competitor ", "")}
                    </span>
                    <div className={styles.breakBarWrap}>
                      <div
                        className={styles.breakBarFill}
                        style={{ width: `${w}%`, background: c.isYou ? "var(--accent-teal)" : p.color, opacity: c.isYou ? 1 : 0.55 }}
                      />
                    </div>
                    <span className={styles.breakScore} style={{ color: scoreColor(s) }}>{s}</span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
