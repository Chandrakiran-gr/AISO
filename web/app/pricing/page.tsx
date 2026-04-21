import type { Metadata } from "next";
import Link from "next/link";
import styles from "./pricing.module.css";

export const metadata: Metadata = {
  title: "Pricing — AISO by Sapienic",
  description: "Start measuring your AI visibility for free. Upgrade when you need more scans, providers, and clients.",
};

const pricingSchema = {
  "@context": "https://schema.org",
  "@type": "ItemList",
  name: "AISO Pricing Plans",
  itemListElement: [
    {
      "@type": "ListItem",
      position: 1,
      item: {
        "@type": "Offer",
        name: "Free",
        description: "1 client, 3 AI platforms, 1 scan per month",
        price: "0",
        priceCurrency: "USD",
      },
    },
    {
      "@type": "ListItem",
      position: 2,
      item: {
        "@type": "Offer",
        name: "Pro",
        description: "Unlimited scans, 4 AI platforms, 5 clients, competitor tracking",
        price: "79",
        priceCurrency: "USD",
      },
    },
  ],
};

const PLANS = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    tagline: "Get started — no credit card",
    cta: "Start free",
    ctaHref: "/signup",
    highlight: false,
    features: [
      "1 client / business",
      "3 AI platforms (ChatGPT, Claude, Perplexity)",
      "1 scan per month",
      "3 intent groups (G1–G3)",
      "AI Visibility Score",
      "Basic competitor snapshot",
      "Email report export",
    ],
  },
  {
    name: "Pro",
    price: "$79",
    period: "/ month",
    tagline: "For serious growth",
    cta: "Start Pro free trial",
    ctaHref: "/signup?plan=pro",
    highlight: true,
    badge: "Most popular",
    features: [
      "5 clients",
      "All 4 AI platforms",
      "Unlimited scans",
      "All 7 intent groups",
      "Full competitor leaderboard",
      "Priority action plan",
      "Trend charts (30-day)",
      "CSV / PDF export",
      "AI Copilot chat (⌘K)",
      "Email & Slack alerts",
    ],
  },
  {
    name: "Agency",
    price: "Custom",
    period: "",
    tagline: "For agencies & enterprises",
    cta: "Contact us",
    ctaHref: "mailto:hello@sapienic.com",
    highlight: false,
    features: [
      "Unlimited clients",
      "White-label reports",
      "API access",
      "Dedicated onboarding",
      "SLA & priority support",
      "Custom intent groups",
      "Team seats",
    ],
  },
];

export default function PricingPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(pricingSchema) }}
      />

      {/* Nav */}
      <nav className={styles.nav} aria-label="Site navigation">
        <Link href="/" className={styles.logo}>
          <span className={styles.logoMark}>◆</span>
          <span className="gradient-text">AISO</span>
        </Link>
        <div className={styles.navActions}>
          <Link href="/login"  className="btn-ghost">Log in</Link>
          <Link href="/signup" className="btn-gradient">Get started free</Link>
        </div>
      </nav>

      {/* Hero */}
      <section className={styles.hero}>
        <div className={styles.heroBadge}>Simple pricing</div>
        <h1 className={styles.heroTitle}>
          Start free,{" "}
          <span className="gradient-text">scale when ready</span>
        </h1>
        <p className={styles.heroSub}>
          No credit card required. Upgrade only when you need more power.
        </p>
      </section>

      {/* Pricing cards */}
      <section className={styles.plansSection} aria-label="Pricing plans">
        <div className={styles.plansGrid}>
          {PLANS.map((plan) => (
            <div
              key={plan.name}
              className={`${styles.planCard} ${plan.highlight ? styles.planCardHighlight : ""}`}
            >
              {plan.badge && (
                <span className={styles.planBadge}>{plan.badge}</span>
              )}
              <div className={styles.planHeader}>
                <h2 className={styles.planName}>{plan.name}</h2>
                <div className={styles.planPrice}>
                  <span className={styles.planAmount}>{plan.price}</span>
                  {plan.period && <span className={styles.planPeriod}>{plan.period}</span>}
                </div>
                <p className={styles.planTagline}>{plan.tagline}</p>
              </div>

              <div className={styles.planDivider} />

              <ul className={styles.featureList} aria-label={`${plan.name} plan features`}>
                {plan.features.map((f) => (
                  <li key={f} className={styles.featureItem}>
                    <span className={styles.featureCheck} aria-hidden="true">✓</span>
                    {f}
                  </li>
                ))}
              </ul>

              <Link
                href={plan.ctaHref}
                className={plan.highlight ? styles.ctaPrimary : styles.ctaSecondary}
                id={`pricing-cta-${plan.name.toLowerCase()}`}
              >
                {plan.cta}
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* FAQ strip */}
      <section className={styles.faqStrip}>
        <div className={styles.faqInner}>
          <h2 className={styles.faqTitle}>Common questions</h2>
          <div className={styles.faqGrid}>
            {[
              {
                q: "Is the free plan really free?",
                a: "Yes — no credit card, no expiry. You get 1 client, 3 platforms, and 1 scan per month forever.",
              },
              {
                q: "Can I switch plans any time?",
                a: "Yes. Upgrade or downgrade at any time. You're never locked in.",
              },
              {
                q: "What counts as a scan?",
                a: "One full pipeline run across your selected AI platforms and intent groups for a single client.",
              },
              {
                q: "Do you offer refunds?",
                a: "Yes — 14-day no-questions-asked refund on Pro.",
              },
            ].map(({ q, a }) => (
              <div key={q} className={styles.faqItem}>
                <h3 className={styles.faqQ}>{q}</h3>
                <p className={styles.faqA}>{a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className={styles.footer}>
        <span className="gradient-text">◆ AISO by Sapienic</span>
        <div className={styles.footerLinks}>
          <Link href="/">Home</Link>
          <Link href="/faq">FAQ</Link>
          <Link href="/about">About</Link>
        </div>
      </footer>
    </>
  );
}
