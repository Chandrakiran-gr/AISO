import Link from "next/link";
import type { Metadata } from "next";
import styles from "./about.module.css";

export const metadata: Metadata = {
  title: "About Sapienic — AI Search Optimization Company",
  description:
    "Sapienic is building the first AI Search Optimization platform. Learn about our mission to help businesses get recommended by ChatGPT, Claude, Perplexity, and Gemini.",
};

const VALUES = [
  { icon: "🎯", title: "Answer-first", sub: "AI platforms reward direct, clear answers. We help you become the best answer." },
  { icon: "📊", title: "Data over gut feel", sub: "Every insight is grounded in real AI response data across 100 questions." },
  { icon: "🔒", title: "Privacy by design", sub: "Your API keys never touch our servers. Zero-persistence BYOK architecture." },
  { icon: "⚡", title: "Speed to insight", sub: "From onboarding to AI Visibility Score in under 10 minutes." },
];

export default function AboutPage() {
  return (
    <div className={styles.page}>
      {/* Nav */}
      <nav className={styles.nav}>
        <Link href="/" className={styles.navLogo}>
          <span className={styles.logoMark}>◆</span>
          <span className="gradient-text">AISO</span>
        </Link>
        <div className={styles.navLinks}>
          <Link href="/pricing" className={styles.navLink}>Pricing</Link>
          <Link href="/faq" className={styles.navLink}>FAQ</Link>
          <Link href="/about" className={`${styles.navLink}`} style={{ color: "var(--text-primary)" }}>About</Link>
          <Link href="/login" className={styles.navCta}>Sign in</Link>
        </div>
      </nav>

      {/* Hero */}
      <section className={styles.hero}>
        <span className={styles.heroEyebrow}>About Sapienic</span>
        <h1 className={styles.heroTitle}>
          The search landscape just changed.<br />We help you win it.
        </h1>
        <p className={styles.heroSub}>
          Sapienic builds tools that measure and improve how AI recommends your business — so when someone asks ChatGPT, Claude, Perplexity, or Gemini for a recommendation, your name comes up.
        </p>
      </section>

      {/* Mission */}
      <section className={styles.section}>
        <div className={styles.missionCard}>
          <p className={styles.missionLabel}>Our mission</p>
          <p className={styles.missionText}>
            Traditional SEO optimizes for <strong>search engine crawlers</strong>. AISO optimizes for <strong>AI language models</strong> — a fundamentally different audience with different signals. We believe every business deserves to be seen in the AI era, not just the ones that got lucky with old-school backlinks.
          </p>
        </div>
      </section>

      {/* Founder */}
      <section className={styles.founderSection}>
        <div className={styles.founderCard}>
          <div className={styles.founderAvatar}>👨‍💻</div>
          <div className={styles.founderInfo}>
            <span className={styles.founderName}>Chandrakiran Guthavariramesh</span>
            <span className={styles.founderRole}>Founder &amp; CEO · Sapienic</span>
            <p className={styles.founderBio}>
              Former ML engineer turned founder. After seeing firsthand how AI search was disrupting organic traffic for clients, I built AISO to give businesses a way to measure and improve their AI visibility — the same way they&apos;ve always tracked SEO rankings.
            </p>
            <div className={styles.founderLinks}>
              <a href="https://linkedin.com/in/chandrakirangr" target="_blank" rel="noopener noreferrer" className={styles.founderLink}>LinkedIn →</a>
              <a href="mailto:chandrakiran.gr25@gmail.com" className={styles.founderLink}>Email →</a>
            </div>
          </div>
        </div>
      </section>

      {/* Values */}
      <section className={styles.valuesSection}>
        <h2 className={styles.sectionTitle}>What we stand for</h2>
        <div className={styles.valuesGrid}>
          {VALUES.map((v) => (
            <div key={v.title} className={styles.valueCard}>
              <div className={styles.valueIcon}>{v.icon}</div>
              <p className={styles.valueTitle}>{v.title}</p>
              <p className={styles.valueSub}>{v.sub}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className={styles.ctaSection}>
        <h2 className={styles.ctaTitle}>Ready to see your AI visibility score?</h2>
        <p className={styles.ctaSub}>Free to start. No credit card required.</p>
        <Link href="/onboarding" className={styles.ctaBtn}>Get your free score →</Link>
      </section>
    </div>
  );
}
