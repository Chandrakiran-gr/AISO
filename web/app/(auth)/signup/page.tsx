import type { Metadata } from "next";
import Link from "next/link";
import styles from "../auth.module.css";
import { signInWithGoogle, signUpWithCredentials } from "../actions";

export const metadata: Metadata = {
  title: "Sign up free — AISO by Sapienic",
  description: "Get your free AI Visibility Score in under 8 minutes. See how ChatGPT, Claude, Perplexity, and Gemini describe your business — and how to rank higher.",
  robots: { index: false, follow: false },
};

const BENEFITS = [
  { icon: "🆓", title: "Free forever tier",       subtitle: "No credit card required" },
  { icon: "⚡", title: "Results in ~8 minutes",   subtitle: "Automated across 4 AI platforms" },
  { icon: "🎯", title: "Actionable steps included", subtitle: "Not just data — a clear action plan" },
];

const GoogleIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" className={styles.oauthIcon}>
    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
  </svg>
);

export default function SignupPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  return <SignupContent searchParams={searchParams} />;
}

async function SignupContent({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const params = await searchParams;
  const errorMessage = getSignupErrorMessage(params.error);

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
            Start measuring your <span className="gradient-text">AI visibility</span> for free.
          </h1>
          <p className={styles.leftSubtitle}>
            Get a complete picture of how ChatGPT, Claude, Perplexity, and Gemini talk about your business — and the exact steps to get recommended more.
          </p>
        </div>
        <div className={styles.leftStats}>
          {BENEFITS.map((b) => (
            <div key={b.title} className={styles.leftStat}>
              <div className={styles.leftStatIcon}>{b.icon}</div>
              <div className={styles.leftStatText}>
                <strong>{b.title}</strong>
                <span>{b.subtitle}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Right Form Panel ── */}
      <div className={styles.right}>
        <div className={styles.formCard}>
          <div className={styles.formHeader}>
            <h2 className={styles.formTitle}>Create your free account</h2>
            <p className={styles.formSubtitle}>AI visibility report in ~8 minutes</p>
          </div>

          {errorMessage && (
            <div className={styles.authAlert} role="alert" aria-live="polite">
              {errorMessage}
            </div>
          )}

          {/* Google OAuth — primary CTA, Server Action */}
          <form
            action={async () => {
              "use server";
              await signInWithGoogle("/onboarding", "/signup");
            }}
          >
            <button type="submit" className={styles.oauthBtn} id="signup-google-btn">
              <GoogleIcon />
              Sign up with Google
            </button>
          </form>

          <div className={styles.dividerRow}>
            <div className={styles.dividerLine} />
            <span>or</span>
            <div className={styles.dividerLine} />
          </div>

          {/* Email sign-up — Server Action */}
          <form
            className={styles.fields}
            action={async (formData: FormData) => {
              "use server";
              await signUpWithCredentials("/onboarding", formData);
            }}
          >
            <div className={styles.fieldGroup}>
              <label className={styles.label} htmlFor="signup-name">Full name</label>
              <input id="signup-name" name="name" type="text" className="input"
                placeholder="Jane Smith" autoComplete="name" required maxLength={120} />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.label} htmlFor="signup-email">Work email</label>
              <input id="signup-email" name="email" type="email" className="input"
                placeholder="jane@company.com" autoComplete="email" required maxLength={254} />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.label} htmlFor="signup-password">Password</label>
              <input id="signup-password" name="password" type="password" className="input"
                placeholder="At least 8 characters" autoComplete="new-password" required minLength={8} maxLength={128} />
            </div>
            <button type="submit" className={styles.submitBtn} id="signup-submit-btn">
              Create free account →
            </button>
          </form>

          <p className={styles.terms}>
            By signing up you agree to our{" "}
            <Link href="/terms">Terms of Service</Link> and{" "}
            <Link href="/privacy">Privacy Policy</Link>.
          </p>

          <p className={styles.switchText}>
            Already have an account? <Link href="/login">Log in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

function getSignupErrorMessage(error?: string): string | null {
  if (!error) return null;

  const messages: Record<string, string> = {
    invalid: "We could not create your account. Please check your details and try again.",
    email_exists: "An account already exists for this email. Log in instead.",
    service_unavailable: "Account creation is temporarily unavailable. Please try again later.",
    signin_failed: "Your account was created, but sign-in failed. Try logging in.",
    CredentialsSignin: "Your account was created, but sign-in failed. Try logging in.",
    OAuthSignin: "Google sign-up could not be started. Please try again.",
    OAuthCallback: "Google sign-up could not be completed. Please try again.",
    OAuthCallbackError: "Google sign-up could not be completed. Please try again.",
    CallbackRouteError: "We could not finish creating your Google account. Please try again.",
    AccessDenied: "Access was denied. Please choose another account or try again.",
    Configuration: "Sign-up is temporarily unavailable. Please try again later.",
  };

  return messages[error] ?? "We could not create your account. Please try again.";
}
