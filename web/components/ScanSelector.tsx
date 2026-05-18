"use client";

import styles from "./ScanSelector.module.css";

export type ScanOption = {
  id: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
};

function formatScanDate(value: string): string {
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ScanSelector({
  id,
  label,
  value,
  scans,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  scans: ScanOption[];
  onChange: (scanId: string) => void;
}) {
  return (
    <label className={styles.field} htmlFor={id}>
      <span>{label}</span>
      <select
        id={id}
        className={styles.select}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {scans.map((scan) => (
          <option key={scan.id} value={scan.id}>
            {formatScanDate(scan.completed_at ?? scan.created_at)} · {scan.status}
          </option>
        ))}
      </select>
    </label>
  );
}
