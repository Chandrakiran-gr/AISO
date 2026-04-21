import styles from "./page.module.css";

export default function DashboardPage() {
  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Dashboard</h1>
          <p className={styles.subtitle}>Your AI visibility at a glance</p>
        </div>
        <button className="btn-gradient">Run New Scan</button>
      </div>

      {/* Placeholder cards — replaced in Phase 3 */}
      <div className={styles.grid}>
        <div className={`card ${styles.scoreCard}`}>
          <div className="skeleton" style={{ width: 120, height: 120, borderRadius: "50%" }} />
          <div style={{ marginTop: 16 }}>
            <div className="skeleton" style={{ width: 140, height: 18, marginBottom: 8 }} />
            <div className="skeleton" style={{ width: 90,  height: 14 }} />
          </div>
        </div>

        {["ChatGPT", "Claude", "Perplexity", "Gemini"].map((p) => (
          <div key={p} className={`card ${styles.providerCard}`}>
            <div className="skeleton" style={{ width: 60, height: 14, marginBottom: 12 }} />
            <div className="skeleton" style={{ width: 80, height: 40, marginBottom: 8 }} />
            <div className="skeleton" style={{ width: 50, height: 12 }} />
            <p className={styles.providerName}>{p}</p>
          </div>
        ))}

        <div className={`card ${styles.chartCard}`}>
          <div className="skeleton" style={{ width: 140, height: 16, marginBottom: 16 }} />
          <div className="skeleton" style={{ width: "100%", height: 120 }} />
        </div>

        <div className={`card ${styles.actionsCard}`}>
          <div className="skeleton" style={{ width: 160, height: 16, marginBottom: 16 }} />
          {[1,2,3].map((i) => (
            <div key={i} className="skeleton" style={{ width: "100%", height: 48, marginBottom: 8, borderRadius: 8 }} />
          ))}
        </div>
      </div>

      <p className={styles.buildNote}>
        🚧 Full dashboard coming in Phase 3 — components, charts, and real data wired in.
      </p>
    </div>
  );
}
