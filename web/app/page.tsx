import type { Metadata } from "next";
import Link from "next/link";
import styles from "./page.module.css";

export const metadata: Metadata = {
  title: "AI Search Optimization Platform — AISO by Sapienic",
  description:
    "Is AI recommending your competitors instead of you? Measure and optimize your brand's visibility across ChatGPT, Claude, Perplexity, and Gemini. Free report in under 3 minutes.",
};

// FAQ structured data — AI models love this
const faqSchema = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What is AI Search Optimization (AISO)?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "AI Search Optimization measures and improves how often AI assistants like ChatGPT, Claude, and Gemini recommend your business when users ask relevant questions. Unlike traditional SEO which targets search engine rankings, AISO optimizes for AI-generated recommendations.",
      },
    },
    {
      "@type": "Question",
      name: "How does AISO measure AI visibility?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "AISO runs hundreds of high-intent questions across 7 intent categories against ChatGPT, Claude, Perplexity, and Gemini simultaneously. It tracks how often your brand is mentioned, in what position, and how often competitors beat you — giving you a single AI Visibility Score from 0 to 100.",
      },
    },
    {
      "@type": "Question",
      name: "Which AI platforms does AISO monitor?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "AISO monitors ChatGPT (OpenAI), Claude (Anthropic), Perplexity, and Gemini (Google). These four platforms collectively handle the majority of AI-powered search queries.",
      },
    },
    {
      "@type": "Question",
      name: "How is AISO different from traditional SEO tools?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Traditional SEO tools track your position in search results pages. AISO tracks whether AI assistants recommend your business in their generated responses — an entirely different distribution channel that is rapidly growing.",
      },
    },
  ],
};

const PROVIDERS = [
  { name: "ChatGPT", color: "var(--provider-openai)" },
  { name: "Claude",  color: "var(--provider-claude)" },
  { name: "Perplexity", color: "var(--provider-perplexity)" },
  { name: "Gemini",  color: "var(--provider-gemini)" },
];

const STATS = [
  { number: "525",  label: "Questions per scan" },
  { number: "4",    label: "AI platforms monitored" },
  { number: "7",    label: "Intent categories" },
  { number: "100%", label: "Automated" },
];

export default function HomePage() {
  return (
    <>
      {/* FAQ JSON-LD */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqSchema) }}
      />

      {/* ── Navigation ── */}
      <nav className="public-nav" aria-label="Main navigation">
        <div className={styles.navLogo}>
          <span className={styles.logoMark}>◆</span>
          <span className={styles.logoName}>
            <span className="gradient-text">AISO</span>
            <span className={styles.logoBy}> by Sapienic</span>
          </span>
        </div>
        <div className={styles.navLinks}>
          <Link href="/platform">Platform</Link>
          <Link href="/pricing">Pricing</Link>
          <Link href="/blog">Blog</Link>
        </div>
        <div className={styles.navActions}>
          <Link href="/login" className="btn-ghost">Log in</Link>
          <Link href="/signup" className="btn-gradient">Get started free</Link>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="hero-section" aria-label="Hero">
        <div className="hero-badge">
          <span>✦</span> AI Search Optimization
        </div>

        <h1 className="hero-title">
          Is AI recommending your{" "}
          <span className="gradient-text">competitors</span>
          {" "}instead of you?
        </h1>

        <p className="hero-subtitle">
          Measure and optimize your brand&apos;s visibility across ChatGPT, Claude,
          Perplexity, and Gemini. Know exactly where you&apos;re losing to competitors
          — and what to do about it.
        </p>

        {/* URL scan form */}
        <div className={styles.heroForm}>
          <div className="hero-url-form">
            <span className={styles.urlIcon}>🔗</span>
            <input
              type="url"
              className="hero-url-input"
              placeholder="https://yourcompany.com"
              aria-label="Enter your website URL for a free AI visibility scan"
            />
            <Link href="/signup" className="btn-gradient" style={{ borderRadius: 12, padding: "10px 20px" }}>
              Scan free →
            </Link>
          </div>

          <div className="hero-trust-line">
            <span>✦ Free</span>
            <span>✦ No credit card</span>
            <span>✦ Results in ~8 minutes</span>
          </div>
        </div>

        {/* Provider pills */}
        <div className={styles.providerRow}>
          <span className={styles.monitoredBy}>Monitored across:</span>
          {PROVIDERS.map((p) => (
            <span
              key={p.name}
              className={styles.providerChip}
              style={{ borderColor: `${p.color}33`, color: p.color }}
            >
              {p.name}
            </span>
          ))}
        </div>
      </section>

      {/* ── Stats strip ── */}
      <section className="stats-strip" aria-label="Platform statistics">
        {STATS.map((s) => (
          <div key={s.label} className="stat-item">
            <div className="stat-number">{s.number}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </section>

      {/* ── Answer-first content (AI extractable) ── */}
      <section className={styles.contentSection} aria-label="What is AI Search Optimization">
        <div className={styles.contentInner}>
          <h2 className={styles.sectionTitle}>
            What is AI Search Optimization?
          </h2>
          <p className={styles.sectionAnswer}>
            AI Search Optimization (AISO) measures how often AI assistants like ChatGPT, Claude,
            and Gemini recommend your business when users ask relevant questions —
            and provides the exact steps to improve that recommendation rate.
          </p>
          <p className={styles.sectionBody}>
            Traditional search engines show users a list of links. AI assistants generate
            direct recommendations, often citing only 2–3 brands. If your business isn&apos;t one
            of them, you&apos;re invisible to a growing share of high-intent buyers.
            AISO ensures you are.
          </p>
        </div>
      </section>

      {/* ── FAQ (AI-extractable, answer-first) ── */}
      <section className={styles.faqSection} aria-label="Frequently asked questions">
        <div className={styles.contentInner}>
          <h2 className={styles.sectionTitle}>Frequently Asked Questions</h2>
          <div className={styles.faqList}>
            {faqSchema.mainEntity.map((q) => (
              <div key={q.name} className={styles.faqItem}>
                <h3 className={styles.faqQuestion}>{q.name}</h3>
                <p className={styles.faqAnswer}>{q.acceptedAnswer.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className={styles.ctaSection} aria-label="Get started">
        <div className={styles.ctaInner}>
          <h2 className={styles.ctaTitle}>
            See your AI Visibility Score{" "}
            <span className="gradient-text">in 8 minutes</span>
          </h2>
          <p className={styles.ctaSubtitle}>
            Free report. No credit card. Real data from ChatGPT, Claude, Perplexity, and Gemini.
          </p>
          <Link href="/signup" className="btn-gradient" style={{ fontSize: "1rem", padding: "14px 32px" }}>
            Get your free report →
          </Link>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className={styles.footer}>
        <div className={styles.footerLogo}>
          <span className="gradient-text">◆ AISO</span>
          <span> by Sapienic</span>
        </div>
        <div className={styles.footerLinks}>
          <Link href="/platform">Platform</Link>
          <Link href="/pricing">Pricing</Link>
          <Link href="/faq">FAQ</Link>
          <Link href="/about">About</Link>
          <Link href="/blog">Blog</Link>
        </div>
        <p className={styles.footerCopy}>
          © {new Date().getFullYear()} Sapienic. All rights reserved.
        </p>
      </footer>
    </>
  );
}
