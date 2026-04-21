import type { Metadata } from "next";
import Link from "next/link";
import styles from "../auth.module.css";

export const metadata: Metadata = {
  title: "Log in — AISO by Sapienic",
  description: "Log in to your AISO dashboard to track your AI visibility across ChatGPT, Claude, Perplexity, and Gemini.",
  robots: { index: false, follow: false },
};

const SOCIAL_PROOF = [
  { icon: "◆", title: "525 questions per scan", subtitle: "Across 7 intent categories" },
  { icon: "🤖", title: "4 AI platforms monitored", subtitle: "ChatGPT, Claude, Perplexity, Gemini" },
  { icon: "📊", title: "Real competitor data", subtitle: "See exactly where you lose" },
];

export default function LoginPage() {
  return (
    <div className={styles.page}>
      <Link href="/" className={styles.backNav}>← Back to home</Link>

      {/* ── Left Branding Panel ── */}
      <div className={styles.left}>
        <div className={styles.leftLogo}>
          <span className={styles.logoMark}>◆</span>
          <span className="gradient-text">AISO</span>
          <span style={{ color: "var(--text-muted)", fontWeight: 400, fontSize: "0.875rem" }}> by Sapienic</span>
        </div>

        <div>
          <h1 className={styles.leftTagline}>
            Know exactly where{" "}
            <span className="gradient-text">AI</span>{" "}
            is sending your customers.
          </h1>
          <p className={styles.leftSubtitle}>
            Your AI Visibility Score measures how often ChatGPT, Claude, Perplexity, and Gemini recommend your business — and gives you the exact steps to improve it.
          </p>
        </div>

        <div className={styles.leftStats}>
          {SOCIAL_PROOF.map((s) => (
            <div key={s.title} className={styles.leftStat}>
              <div className={styles.leftStatIcon}>{s.icon}</div>
              <div className={styles.leftStatText}>
                <strong>{s.title}</strong>
                <span>{s.subtitle}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Right Form Panel ── */}
      <div className={styles.right}>
        <div className={styles.formCard}>
          <div className={styles.formHeader}>
            <h2 className={styles.formTitle}>Welcome back</h2>
            <p className={styles.formSubtitle}>Log in to your AISO dashboard</p>
          </div>

          {/* Google OAuth */}
          <form action="/api/auth/signin/google" method="POST">
            <input type="hidden" name="callbackUrl" value="/dashboard" />
            <button type="submit" className={styles.oauthBtn} id="login-google-btn">
              <svg className={styles.oauthIcon} viewBox="0 0 24 24" aria-hidden="true">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
              </svg>
              Continue with Google
            </button>
          </form>

          <div className={styles.dividerRow}>
            <div className={styles.dividerLine} />
            <span>or</span>
            <div className={styles.dividerLine} />
          </div>

          {/* Email / password */}
          <form className={styles.fields} action="/api/auth/signin/credentials" method="POST">
            <input type="hidden" name="callbackUrl" value="/dashboard" />

            <div className={styles.fieldGroup}>
              <label className={styles.label} htmlFor="login-email">Email address</label>
              <input
                id="login-email"
                name="email"
                type="email"
                className="input"
                placeholder="you@company.com"
                autoComplete="email"
                required
                maxLength={254}
              />
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.label} htmlFor="login-password">Password</label>
              <input
                id="login-password"
                name="password"
                type="password"
                className="input"
                placeholder="••••••••"
                autoComplete="current-password"
                required
                minLength={8}
                maxLength={128}
              />
            </div>

            <button type="submit" className={styles.submitBtn} id="login-submit-btn">
              Log in
            </button>
          </form>

          <p className={styles.switchText}>
            Don&apos;t have an account?{" "}
            <Link href="/signup">Sign up free</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
