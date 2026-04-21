import type { Metadata } from "next";
import Link from "next/link";
import styles from "./faq.module.css";

export const metadata: Metadata = {
  title: "FAQ — AISO by Sapienic",
  description: "Answers to common questions about AI Search Optimization, how AISO measures AI visibility, and what you can do to improve your AI recommendations.",
};

const faqSchema = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What is AI Search Optimization (AISO)?",
      acceptedAnswer: { "@type": "Answer", text: "AI Search Optimization (AISO) is the practice of measuring and improving how often AI assistants like ChatGPT, Claude, Perplexity, and Gemini recommend your business when users ask relevant questions. It's the equivalent of SEO, but for AI-generated answers instead of search engine rankings." },
    },
    {
      "@type": "Question",
      name: "How is AISO different from traditional SEO?",
      acceptedAnswer: { "@type": "Answer", text: "Traditional SEO optimizes your position in a list of links. AISO optimizes whether AI assistants recommend your business in their generated responses — often citing only 2–3 brands. These are fundamentally different distribution channels requiring different optimization strategies." },
    },
    {
      "@type": "Question",
      name: "What is an AI Visibility Score?",
      acceptedAnswer: { "@type": "Answer", text: "Your AI Visibility Score is a 0–100 metric that represents how prominently your business is recommended across AI platforms. It's calculated from mention rate, position, and sentiment across ChatGPT, Claude, Perplexity, and Gemini for queries relevant to your business." },
    },
    {
      "@type": "Question",
      name: "Which AI platforms does AISO monitor?",
      acceptedAnswer: { "@type": "Answer", text: "AISO currently monitors ChatGPT (OpenAI), Claude (Anthropic), Perplexity, and Gemini (Google). These four platforms handle the vast majority of AI search queries worldwide." },
    },
    {
      "@type": "Question",
      name: "How long does a scan take?",
      acceptedAnswer: { "@type": "Answer", text: "A standard scan takes approximately 8 minutes. AISO runs hundreds of questions across multiple AI platforms in parallel to keep scan time as short as possible." },
    },
    {
      "@type": "Question",
      name: "What are intent groups (G1–G7)?",
      acceptedAnswer: { "@type": "Answer", text: "Intent groups are the 7 categories of questions AISO uses to evaluate your AI visibility: G1 Awareness (discovery), G2 Comparison (vs competitors), G3 Transactional (purchase intent), G4 Local (location-based), G5 Technical (features/specs), G6 Trust (reviews/reputation), and G7 Support (post-purchase). Each group reveals different aspects of your AI presence." },
    },
    {
      "@type": "Question",
      name: "What can I do to improve my AI Visibility Score?",
      acceptedAnswer: { "@type": "Answer", text: "AISO provides a prioritized action plan with each scan. Key improvement strategies include: publishing answer-first content that AI models prefer, building structured entity data (Schema.org, Wikipedia, Wikidata), getting listed on authoritative platforms that AI models cite, and ensuring consistent brand information across the web." },
    },
    {
      "@type": "Question",
      name: "Is AISO's free plan actually free?",
      acceptedAnswer: { "@type": "Answer", text: "Yes. The free plan includes 1 client, 3 AI platforms, and 1 scan per month with no credit card required and no expiry date." },
    },
  ],
};

export default function FAQPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqSchema) }}
      />

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

      <main className={styles.main}>
        <div className={styles.inner}>
          <div className={styles.hero}>
            <h1 className={styles.heroTitle}>Frequently Asked Questions</h1>
            <p className={styles.heroSub}>
              Everything you need to know about AI Search Optimization and how AISO works.
            </p>
          </div>

          <div className={styles.faqList} role="list">
            {faqSchema.mainEntity.map((item) => (
              <div key={item.name} className={styles.faqItem} role="listitem">
                <h2 className={styles.question}>{item.name}</h2>
                <p className={styles.answer}>{item.acceptedAnswer.text}</p>
              </div>
            ))}
          </div>

          <div className={styles.cta}>
            <h2 className={styles.ctaTitle}>Still have questions?</h2>
            <p className={styles.ctaSub}>
              Start a free scan and explore AISO firsthand — no credit card required.
            </p>
            <Link href="/signup" className="btn-gradient">Get your free report →</Link>
          </div>
        </div>
      </main>
    </>
  );
}
