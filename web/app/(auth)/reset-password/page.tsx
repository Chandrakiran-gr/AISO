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
  description: "Choose a new password for your AISO account.",
  robots: { index: false, follow: false },
};

export default function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string; error?: string }>;
}) {
  return <ResetContent searchParams={searchParams} />;
}

async function ResetContent({
  searchParams,
}: {
  searchParams: Promise<{ token?: string; error?: string }>;
}) {
  const params = await searchParams;
  const token = params.token ?? "";
  const errorMessage = getResetErrorMessage(params.error);
  // No token (or an invalid/expired one) — the link can't be used; send them back.
  const linkUnusable = !token || params.error === "invalid_token";

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
            Pick a new password for your AISO account. You opened this from your reset email, so no code needed.
          </p>
        </div>
      </div>

      <div className={styles.right}>
        <div className={styles.formCard}>
          {linkUnusable ? (
            <>
              <div className={styles.formHeader}>
                <h2 className={styles.formTitle}>This link can&apos;t be used</h2>
                <p className={styles.formSubtitle}>
                  Reset links expire after 15 minutes and work only once.
                </p>
              </div>
              <div className={styles.authAlert} role="alert" aria-live="polite">
                Please <Link href="/forgot-password">request a new reset link</Link>.
              </div>
              <p className={styles.switchText}>
                Remembered it? <Link href="/login">Back to log in</Link>
              </p>
            </>
          ) : (
            <>
              <div className={styles.formHeader}>
                <h2 className={styles.formTitle}>Set a new password</h2>
                <p className={styles.formSubtitle}>Choose a new password for your account</p>
              </div>

              {errorMessage && (
                <div className={styles.authAlert} role="alert" aria-live="polite">{errorMessage}</div>
              )}

              <form className={styles.fields} action={resetPasswordAction}>
                <input type="hidden" name="token" defaultValue={token} />
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
                Remembered it? <Link href="/login">Back to log in</Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function getResetErrorMessage(error?: string): string | null {
  if (!error) return null;
  // invalid_token is handled by the "link can't be used" state, not an inline message.
  if (error === "invalid_token") return null;
  const messages: Record<string, string> = {
    validation_error: "That password doesn't meet the requirements.",
  };
  return messages[error] ?? "We couldn't reset your password. Please try again.";
}
