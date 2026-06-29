import type { Metadata } from "next";
import Link from "next/link";
import styles from "../auth.module.css";
import { forgotPasswordAction } from "../actions";

export const metadata: Metadata = {
  title: "Reset your password — AISO by Sapienic",
  description: "Request a link to reset your AISO password.",
  robots: { index: false, follow: false },
};

export default function ForgotPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ sent?: string }>;
}) {
  return <ForgotContent searchParams={searchParams} />;
}

async function ForgotContent({
  searchParams,
}: {
  searchParams: Promise<{ sent?: string }>;
}) {
  const sent = (await searchParams).sent === "1";

  return (
    <div className={styles.page}>
      <Link href="/" className={styles.backNav}>← Back to home</Link>

      <div className={styles.left}>
        <div className={styles.leftLogo}>
          <span className={styles.logoMark}>◆</span>
          <span className="gradient-text">AISO</span>
          <span style={{ color: "var(--text-muted)", fontWeight: 400, fontSize: "0.875rem" }}> by Sapienic</span>
        </div>
        <div>
          <h1 className={styles.leftTagline}>
            Locked out? <span className="gradient-text">Back in</span> in two steps.
          </h1>
          <p className={styles.leftSubtitle}>
            Enter your email and we&apos;ll send a secure link to reset your password.
          </p>
        </div>
      </div>

      <div className={styles.right}>
        <div className={styles.formCard}>
          {sent ? (
            <>
              <div className={styles.formHeader}>
                <h2 className={styles.formTitle}>Check your email</h2>
                <p className={styles.formSubtitle}>
                  If an account exists for that address, we&apos;ve emailed a link to reset your password. It expires in 30 minutes.
                </p>
              </div>
              <div className={styles.authAlert} role="status" aria-live="polite">
                Didn&apos;t get it? Check spam, or <Link href="/forgot-password">request another link</Link>.
              </div>
              <p className={styles.switchText}>
                Remembered it? <Link href="/login">Back to log in</Link>
              </p>
            </>
          ) : (
            <>
              <div className={styles.formHeader}>
                <h2 className={styles.formTitle}>Forgot your password?</h2>
                <p className={styles.formSubtitle}>We&apos;ll email you a reset link</p>
              </div>

              <form className={styles.fields} action={forgotPasswordAction}>
                <div className={styles.fieldGroup}>
                  <label className={styles.label} htmlFor="forgot-email">Email address</label>
                  <input
                    id="forgot-email"
                    name="email"
                    type="email"
                    className="input"
                    placeholder="you@company.com"
                    autoComplete="email"
                    required
                    maxLength={254}
                  />
                </div>
                <button type="submit" className={styles.submitBtn}>Send reset link →</button>
              </form>

              <p className={styles.switchText}>
                Remembered it? <Link href="/login">Back to log in</Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
