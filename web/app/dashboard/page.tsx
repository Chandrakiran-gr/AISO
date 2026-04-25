"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { useSession, signOut } from "next-auth/react";
import styles from "./dashboard.module.css";

export const dynamic = "force-dynamic";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────────
interface ScanData {
  id: string;
  status: string;
  providers: string[];
  created_at: string;
  skipped_providers?: string[];
}

// ── Defaults shown while loading / when no real scan exists ───────────────────
const PLACEHOLDER_PROVIDERS = [
  { id: "openai",     name: "ChatGPT",    color: "#10a37f", score: 0, mentions: 0, total: 100 },
  { id: "claude",     name: "Claude",     color: "#e8b68a", score: 0, mentions: 0, total: 100 },
  { id: "perplexity", name: "Perplexity", color: "#1fb8cd", score: 0, mentions: 0, total: 100 },
  { id: "gemini",     name: "Gemini",     color: "#4285f4", score: 0, mentions: 0, total: 100 },
];

const PLACEHOLDER_GROUPS = [
  { id: "G1", label: "Awareness",  score: 0 },
  { id: "G2", label: "Comparison", score: 0 },
  { id: "G3", label: "Transact",   score: 0 },
  { id: "G4", label: "Local",      score: 0 },
  { id: "G5", label: "Technical",  score: 0 },
  { id: "G6", label: "Trust",      score: 0 },
  { id: "G7", label: "Support",    score: 0 },
];

const MOCK_COMPETITORS = [
  { name: "Competitor A",  score: 71, isYou: false },
  { name: "Competitor B",  score: 58, isYou: false },
  { name: "Your Business", score: 42, isYou: true  },
  { name: "Competitor C",  score: 35, isYou: false },
  { name: "Competitor D",  score: 28, isYou: false },
];

const MOCK_ACTIONS = [
  { priority: "high",   title: "Add entity disambiguation to your homepage",           sub: "G6 Trust · Add Schema.org LocalBusiness markup" },
  { priority: "high",   title: "Publish a direct answer to 'who is the best [category]?'", sub: "G2 Comparison · Absent from 94% of comparison queries on Claude" },
  { priority: "medium", title: "Get listed on 3 more authoritative directories",        sub: "G1 Awareness · Yelp, BBB, G2 are top AI citation sources" },
  { priority: "medium", title: "Create a FAQ page targeting G5 technical questions",   sub: "G5 Technical · Answer-first content improves AI citation" },
  { priority: "low",    title: "Add customer review schema (AggregateRating)",         sub: "G6 Trust · Structured review data increases citations by ~18%" },
];

const NAV = [
  { icon: "📊", label: "Overview",     href: "/dashboard",             active: true  },
  { icon: "🔍", label: "Scan History", href: "/dashboard/scans",       active: false },
  { icon: "🏆", label: "Competitors",  href: "/dashboard/competitors", active: false },
  { icon: "⚡", label: "Action Plan",  href: "/dashboard/actions",     active: false },
  { icon: "⚙️", label: "Settings",     href: "/dashboard/settings",    active: false },
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
  const [widths, setWidths] = useState<number[]>(PLACEHOLDER_GROUPS.map(() => 0));
  useEffect(() => {
    const t = setTimeout(() => setWidths(PLACEHOLDER_GROUPS.map((g) => g.score)), 300);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <h2 className={styles.cardTitle}>Intent Group Breakdown</h2>
        <span className={styles.cardBadge}>7 groups</span>
      </div>
      <div className={styles.groupList}>
        {PLACEHOLDER_GROUPS.map((g, i) => (
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
  const { data: session } = useSession();
  const [latestScan, setLatestScan] = useState<ScanData | null>(null);
  const [clientId, setClientId]     = useState<string | null>(null);
  const [loading, setLoading]       = useState(true);

  // Fetch first client → latest scan on mount
  useEffect(() => {
    async function load() {
      try {
        const clientsRes = await fetch(`${API}/api/v1/clients`);
        if (!clientsRes.ok) return;
        const clients: { id: string; name: string }[] = await clientsRes.json();
        if (!clients.length) return;
        const cid = clients[0].id;
        setClientId(cid);
        const scansRes = await fetch(`${API}/api/v1/clients/${cid}/scans`);
        if (!scansRes.ok) return;
        const scans: ScanData[] = await scansRes.json();
        if (scans.length) setLatestScan(scans[0]);
      } catch { /* API offline — show placeholders */ }
      finally { setLoading(false); }
    }
    load();
  }, []);

  const scanRunning = latestScan?.status === "running" || latestScan?.status === "pending";
  const lastScanDate = latestScan
    ? new Date(latestScan.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : null;
  const userEmail = session?.user?.email ?? "—";

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
            <Link key={item.href} href={item.href}
              className={`${styles.navItem} ${item.active ? styles.active : ""}`}>
              <span className={styles.navIcon}>{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </div>
        <div className={styles.sidebarSpacer} />
        <div className={styles.sidebarFooter}>
          <span className={styles.userEmail}>{userEmail}</span>
          <button className={styles.signOutBtn} onClick={() => signOut({ callbackUrl: "/" })}>
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className={styles.main}>
        <div className={styles.topBar}>
          <div className={styles.topBarLeft}>
            <span className={styles.pageTitle}>Overview</span>
            <span className={styles.pageSub}>
              {loading ? "Loading…"
                : lastScanDate ? `Last scan: ${lastScanDate} · ${latestScan?.providers?.length ?? 0} platforms`
                : "No scans yet — run your first scan"}
            </span>
          </div>
          <div className={styles.topBarRight}>
            <Link href="/onboarding" className={styles.newScanBtn}>▶ New scan</Link>
          </div>
        </div>

        <section className={styles.content}>
          {/* Scan running banner */}
          {scanRunning && (
            <div className={styles.scanBanner}>
              <div className={styles.scanBannerSpinner} />
              <p className={styles.scanBannerText}>
                <strong>Scan in progress</strong> — querying AI platforms across 100 questions.
              </p>
            </div>
          )}

          {/* No scans yet — empty CTA */}
          {!loading && !latestScan && (
            <div style={{ textAlign: "center", padding: "var(--space-2xl) 0" }}>
              <p style={{ fontSize: "2rem", marginBottom: 8 }}>🔍</p>
              <p style={{ fontWeight: 600, marginBottom: 4 }}>No scans yet</p>
              <p style={{ color: "var(--text-muted)", fontSize: "0.875rem", marginBottom: 24 }}>
                Run your first AI visibility scan to see your score.
              </p>
              <Link href="/onboarding" className={styles.newScanBtn}>▶ Run first scan</Link>
            </div>
          )}

          {/* Score ring + provider cards */}
          <div className={styles.heroRow}>
            <ScoreRing score={latestScan ? 42 : 0} delta={0} />
            <div className={styles.providerGrid}>
              {PLACEHOLDER_PROVIDERS.map((p) => <ProviderCard key={p.id} {...p} />)}
            </div>
          </div>

          {/* Group breakdown + competitor leaderboard */}
          <div className={styles.sectionRow}>
            <GroupChart />
            <CompetitorBoard />
          </div>

          {/* Action items */}
          <div className={styles.sectionRow}>
            <ActionItems />
          </div>
        </section>
      </main>
    </div>
  );
}
