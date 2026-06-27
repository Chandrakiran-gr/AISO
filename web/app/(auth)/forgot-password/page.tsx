import type { Metadata } from "next";
import Link from "next/link";
import styles from "../auth.module.css";
import { forgotPasswordAction } from "../actions";

export const metadata: Metadata = {
  title: "Reset your password — AISO by Sapienic",
  description: "Request a code to reset your AISO password.",
  robots: { index: false, follow: false },
};

export default function ForgotPasswordPage() {
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
            Enter your email and we&apos;ll send a 6-digit code to reset your password.
          </p>
        </div>
      </div>

      <div className={styles.right}>
        <div className={styles.formCard}>
          <div className={styles.formHeader}>
            <h2 className={styles.formTitle}>Forgot your password?</h2>
            <p className={styles.formSubtitle}>We&apos;ll email you a reset code</p>
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
            <button type="submit" className={styles.submitBtn}>Send reset code →</button>
          </form>

          <p className={styles.switchText}>
            Remembered it? <Link href="/login">Back to log in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
