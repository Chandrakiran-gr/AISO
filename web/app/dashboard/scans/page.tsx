"use client";

import Link from "next/link";
import styles from "./scans.module.css";

const NAV = [
  { icon: "📊", label: "Overview",    href: "/dashboard",              active: false },
  { icon: "🔍", label: "Scan History", href: "/dashboard/scans",       active: true  },
  { icon: "🏆", label: "Competitors",  href: "/dashboard/competitors", active: false },
  { icon: "⚡", label: "Action Plan",  href: "/dashboard/actions",     active: false },
  { icon: "⚙️", label: "Settings",     href: "/dashboard/settings",    active: false },
];

const PROVIDERS = [
  { id: "openai",     color: "#10a37f" },
  { id: "claude",     color: "#e8b68a" },
  { id: "perplexity", color: "#1fb8cd" },
  { id: "gemini",     color: "#4285f4" },
];

// ── Mock scan history (Phase 4 will wire to FastAPI) ──────────────────────────
const MOCK_SCANS = [
  {
    id: "scan-004",
    date: "Today · 9:42 AM",
    dateISO: "2026-04-24",
    providers: ["openai", "claude", "perplexity", "gemini"],
    questions: 100,
    score: 42,
    delta: +6,
    status: "complete",
  },
  {
    id: "scan-003",
    date: "Apr 17 · 2:15 PM",
    dateISO: "2026-04-17",
    providers: ["openai", "perplexity", "gemini"],
    questions: 100,
    score: 36,
    delta: -2,
    status: "complete",
  },
  {
    id: "scan-002",
    date: "Apr 10 · 11:08 AM",
    dateISO: "2026-04-10",
    providers: ["openai", "claude", "perplexity", "gemini"],
    questions: 100,
    score: 38,
    delta: +4,
    status: "complete",
  },
  {
    id: "scan-001",
    date: "Apr 3 · 9:00 AM",
    dateISO: "2026-04-03",
    providers: ["openai", "perplexity"],
    questions: 100,
    score: 34,
    delta: 0,
    status: "complete",
  },
];

const STATS = [
  { label: "Total scans",      value: "4"   },
  { label: "Best score",       value: "42"  },
  { label: "Latest score",     value: "42"  },
  { label: "Score trend",      value: "+6"  },
];

type DeltaClass = "up" | "down" | "same";

function deltaClass(d: number): DeltaClass {
  if (d > 0) return "up";
  if (d < 0) return "down";
  return "same";
}

function deltaLabel(d: number): string {
  if (d > 0) return `↑ +${d} pts`;
  if (d < 0) return `↓ ${d} pts`;
  return "no change";
}

function scoreColor(score: number): string {
  if (score >= 60) return "var(--accent-teal)";
  if (score >= 35) return "#f59e0b";
  return "#ef4444";
}

export default function ScansPage() {
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
        <div className={styles.topBar}>
          <div className={styles.topBarLeft}>
            <span className={styles.pageTitle}>Scan History</span>
            <span className={styles.pageSub}>All past AI visibility scans for this business</span>
          </div>
          <Link href="/onboarding" className={styles.newScanBtn}>
            ▶ New scan
          </Link>
        </div>

        <div className={styles.content}>
          {/* Stats row */}
          <div className={styles.statsRow}>
            {STATS.map((s) => (
              <div key={s.label} className={styles.statCard}>
                <span className={styles.statValue}>{s.value}</span>
                <span className={styles.statLabel}>{s.label}</span>
              </div>
            ))}
          </div>

          {/* Scan list */}
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>All scans</h2>
            <span className={styles.sectionHint}>{MOCK_SCANS.length} runs total</span>
          </div>

          {MOCK_SCANS.length === 0 ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>🔍</div>
              <p className={styles.emptyTitle}>No scans yet</p>
              <p className={styles.emptySub}>
                Run your first AI visibility scan to start tracking how often AI platforms mention your business.
              </p>
              <Link href="/onboarding" className={styles.newScanBtn}>
                ▶ Run first scan
              </Link>
            </div>
          ) : (
            <div className={styles.scanList}>
              {MOCK_SCANS.map((scan) => (
                <Link
                  key={scan.id}
                  href={`/dashboard/scans/${scan.id}`}
                  className={styles.scanRow}
                  aria-label={`Scan from ${scan.date}, score ${scan.score}`}
                >
                  {/* Date + providers */}
                  <div className={styles.scanMeta}>
                    <span className={styles.scanDate}>{scan.date}</span>
                    <span className={styles.scanProviders}>
                      {scan.providers.map((pid) => {
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
                      {scan.questions} questions · {scan.providers.length} platforms
                    </span>
                  </div>

                  {/* Score */}
                  <span
                    className={styles.scanScore}
                    style={{ color: scoreColor(scan.score) }}
                  >
                    {scan.score}
                  </span>

                  {/* Delta */}
                  <span className={`${styles.scanDelta} ${styles[deltaClass(scan.delta)]}`}>
                    {deltaLabel(scan.delta)}
                  </span>

                  {/* Status */}
                  <span className={`${styles.statusBadge} ${styles[scan.status as "complete" | "running" | "failed" | "pending"]}`}>
                    {scan.status}
                  </span>

                  {/* Arrow */}
                  <span className={styles.viewBtn}>View →</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
