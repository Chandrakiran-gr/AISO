"use client";

import { useState } from "react";
import styles from "./auth.module.css";

type PasswordFieldProps = {
  id: string;
  name: string;
  placeholder: string;
  autoComplete: string;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  title?: string;
  describedBy?: string;
};

export function PasswordField({
  describedBy,
  ...props
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className={styles.passwordWrap}>
      <input
        {...props}
        type={visible ? "text" : "password"}
        className={`input ${styles.passwordInput}`}
        aria-describedby={describedBy}
      />
      <button
        type="button"
        className={styles.passwordToggle}
        onClick={() => setVisible((current) => !current)}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
      >
        {visible ? "Hide" : "Show"}
      </button>
    </div>
  );
}
