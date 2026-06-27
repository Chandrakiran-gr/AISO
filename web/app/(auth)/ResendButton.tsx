"use client";

import { useEffect, useState } from "react";
import styles from "./auth.module.css";
import { resendOtpAction } from "./actions";

// Matches the backend RESEND_COOLDOWN (api/auth_otp.py). The button is frozen for
// this long after each page load (a code is sent on signup and on each resend),
// so the user can't trip the server-side cooldown.
const COOLDOWN_SECONDS = 60;

export function ResendButton({ email }: { email: string }) {
  const [secs, setSecs] = useState(COOLDOWN_SECONDS);

  useEffect(() => {
    const timer = setInterval(() => setSecs((s) => (s <= 1 ? 0 : s - 1)), 1000);
    return () => clearInterval(timer);
  }, []);

  const waiting = secs > 0;

  return (
    <form action={resendOtpAction} style={{ marginTop: 12 }}>
      <input type="hidden" name="email" defaultValue={email} />
      <button
        type="submit"
        className={styles.oauthBtn}
        disabled={waiting}
        aria-live="polite"
        style={waiting ? { opacity: 0.55, cursor: "not-allowed" } : undefined}
      >
        {waiting ? `Resend code in ${secs}s` : "Resend code"}
      </button>
    </form>
  );
}
