import type { Metadata } from "next";
import Link from "next/link";
import styles from "../auth.module.css";
import { resetPasswordAction } from "../actions";
import { PasswordField } from "../PasswordField";

const PASSWORD_PATTERN =
  "(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[^A-Za-z0-9\\s]).{8,}";
const PASSWORD_POLICY =
  "Use at least 8 characters with uppercase, lowercase, number, and special character.";

export const metadata: Metadata = {
  title: "Set a new password — AISO by Sapienic",
  description: "Enter your reset code and choose a new AISO password.",
  robots: { index: false, follow: false },
};

export default function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string; error?: string }>;
}) {
  return <ResetContent searchParams={searchParams} />;
}

async function ResetContent({
  searchParams,
}: {
  searchParams: Promise<{ email?: string; error?: string }>;
}) {
  const params = await searchParams;
  const email = params.email ?? "";
  const errorMessage = getResetErrorMessage(params.error);

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
            Choose a <span className="gradient-text">new password</span>.
          </h1>
          <p className={styles.leftSubtitle}>
            Enter the 6-digit code we emailed you and pick a new password for your AISO account.
          </p>
        </div>
      </div>

      <div className={styles.right}>
        <div className={styles.formCard}>
          <div className={styles.formHeader}>
            <h2 className={styles.formTitle}>Set a new password</h2>
            <p className={styles.formSubtitle}>
              {email ? (
                <>Enter the code sent to <strong>{email}</strong></>
              ) : (
                "Enter your reset code and a new password"
              )}
            </p>
          </div>

          {errorMessage && (
            <div className={styles.authAlert} role="alert" aria-live="polite">{errorMessage}</div>
          )}

          <form className={styles.fields} action={resetPasswordAction}>
            <input type="hidden" name="email" defaultValue={email} />
            <div className={styles.fieldGroup}>
              <label className={styles.label} htmlFor="reset-code">Reset code</label>
              <input
                id="reset-code"
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
            <div className={styles.fieldGroup}>
              <label className={styles.label} htmlFor="reset-password">New password</label>
              <PasswordField
                id="reset-password"
                name="new_password"
                placeholder="At least 8 characters"
                autoComplete="new-password"
                required
                minLength={8}
                maxLength={128}
                pattern={PASSWORD_PATTERN}
                title={PASSWORD_POLICY}
                describedBy="reset-password-help"
              />
              <p className={styles.passwordHelp} id="reset-password-help">{PASSWORD_POLICY}</p>
            </div>
            <button type="submit" className={styles.submitBtn}>Reset password →</button>
          </form>

          <p className={styles.switchText}>
            Didn&apos;t get a code? <Link href="/forgot-password">Request another</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

function getResetErrorMessage(error?: string): string | null {
  if (!error) return null;
  const messages: Record<string, string> = {
    invalid_code: "That code is incorrect. Please check and try again.",
    code_expired: "That code has expired. Request a new one.",
    too_many_attempts: "Too many attempts. Request a new code and try again.",
    validation_error: "That password doesn't meet the requirements.",
  };
  return messages[error] ?? "We couldn't reset your password. Please try again.";
}
