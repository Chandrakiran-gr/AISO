import type { Metadata } from "next";
import Link from "next/link";
import styles from "../auth.module.css";
import { verifyOtpAction } from "../actions";
import { ResendButton } from "../ResendButton";

export const metadata: Metadata = {
  title: "Verify your email — AISO by Sapienic",
  description: "Enter the code we emailed to verify your AISO account.",
  robots: { index: false, follow: false },
};

export default function VerifyPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string; error?: string; resent?: string }>;
}) {
  return <VerifyContent searchParams={searchParams} />;
}

async function VerifyContent({
  searchParams,
}: {
  searchParams: Promise<{ email?: string; error?: string; resent?: string }>;
}) {
  const params = await searchParams;
  const email = params.email ?? "";
  const errorMessage = getOtpErrorMessage(params.error);
  const resent = params.resent === "1";

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
            One quick step to <span className="gradient-text">secure</span> your account.
          </h1>
          <p className={styles.leftSubtitle}>
            We emailed a 6-digit code to confirm it&apos;s really you. Enter it to finish setting up your AISO account.
          </p>
        </div>
      </div>

      <div className={styles.right}>
        <div className={styles.formCard}>
          <div className={styles.formHeader}>
            <h2 className={styles.formTitle}>Verify your email</h2>
            <p className={styles.formSubtitle}>
              {email ? (
                <>Enter the 6-digit code sent to <strong>{email}</strong></>
              ) : (
                "Enter the 6-digit code we emailed you"
              )}
            </p>
          </div>

          {errorMessage && (
            <div className={styles.authAlert} role="alert" aria-live="polite">{errorMessage}</div>
          )}
          {resent && !errorMessage && (
            <div className={styles.authAlert} role="status" aria-live="polite">
              A new code is on its way.
            </div>
          )}

          <form className={styles.fields} action={verifyOtpAction}>
            <input type="hidden" name="email" defaultValue={email} />
            <div className={styles.fieldGroup}>
              <label className={styles.label} htmlFor="otp-code">Verification code</label>
              <input
                id="otp-code"
                name="code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                className="input"
                placeholder="123456"
                required
                pattern="[0-9]{6}"
                maxLength={6}
                title="Enter the 6-digit code"
              />
            </div>
            <button type="submit" className={styles.submitBtn}>Verify &amp; continue →</button>
          </form>

          <ResendButton email={email} />

          <p className={styles.switchText}>
            Wrong email? <Link href="/signup">Sign up again</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

function getOtpErrorMessage(error?: string): string | null {
  if (!error) return null;
  const messages: Record<string, string> = {
    invalid_code: "That code is incorrect. Please check and try again.",
    code_expired: "That code has expired. Request a new one.",
    too_many_attempts: "Too many attempts. Request a new code and try again.",
    no_code: "No active code found. Request a new one.",
    email_send_failed: "We couldn't send the email. Please try again shortly.",
    resend_failed: "Couldn't resend just yet. Please wait a moment and try again.",
    rate_limited: "Please wait a moment before requesting another code.",
  };
  return messages[error] ?? "Verification failed. Please try again.";
}
