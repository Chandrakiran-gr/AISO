import Link from "next/link";
import styles from "./upgrade.module.css";

const PRO_FEATURES = [
  "CSV and PDF exports",
  "Unlimited scans",
  "Managed provider keys",
  "Full competitor leaderboard",
];

const PLAN_ROWS = [
  { label: "Clients", free: "1 business", pro: "5 businesses" },
  { label: "Scans", free: "1 per month", pro: "Unlimited" },
  { label: "Provider keys", free: "Bring your own", pro: "Managed for you" },
  { label: "Exports", free: "Email report", pro: "CSV and PDF" },
];

export default function UpgradePage() {
  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.pageTitle}>Upgrade</h1>
          <p className={styles.pageSub}>Unlock Pro inside your AISO workspace</p>
        </div>
        <Link href="/dashboard/scans" className={styles.backBtn}>
          Back to scans
        </Link>
      </header>

      <main className={styles.content}>
        <section className={styles.heroPanel}>
          <div className={styles.heroCopy}>
            <span className={styles.planBadge}>Pro</span>
            <h2>Unlock professional exports</h2>
            <p>
              Export scan evidence, visibility data, and report-ready files without leaving the dashboard.
            </p>
            <div className={styles.ctaRow}>
              <a
                href="mailto:hello@sapienic.com?subject=AISO%20Pro%20upgrade"
                className={styles.primaryBtn}
              >
                Upgrade to Pro
              </a>
              <Link href="/dashboard" className={styles.secondaryBtn}>
                Not now
              </Link>
            </div>
          </div>

          <div className={styles.pricePanel}>
            <span className={styles.price}>$79</span>
            <span className={styles.period}>/ month</span>
            <p>Built for teams running AISO as an ongoing visibility system.</p>
          </div>
        </section>

        <section className={styles.featureGrid} aria-label="Pro features">
          {PRO_FEATURES.map((feature) => (
            <div key={feature} className={styles.featureCard}>
              <span className={styles.featureDot} />
              <span>{feature}</span>
            </div>
          ))}
        </section>

        <section className={styles.comparePanel} aria-label="Plan comparison">
          <div className={styles.compareHeader}>
            <span>Feature</span>
            <span>Free</span>
            <span>Pro</span>
          </div>
          {PLAN_ROWS.map((row) => (
            <div key={row.label} className={styles.compareRow}>
              <span>{row.label}</span>
              <span>{row.free}</span>
              <strong>{row.pro}</strong>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
