"use client";

import styles from "./MetricDeltaBadge.module.css";

type ImprovedWhen = "up" | "down" | "neutral";

function formatDelta(value: number, decimals: number, suffix: string): string {
  const rounded = Number(value.toFixed(decimals));
  const abs = Math.abs(rounded).toLocaleString("en-US", {
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals > 0 ? decimals : 0,
  });
  if (rounded > 0) return `+${abs}${suffix}`;
  if (rounded < 0) return `-${abs}${suffix}`;
  return `0${suffix}`;
}

export default function MetricDeltaBadge({
  value,
  suffix = "",
  decimals = 0,
  improvedWhen = "up",
}: {
  value: number;
  suffix?: string;
  decimals?: number;
  improvedWhen?: ImprovedWhen;
}) {
  const direction = value > 0 ? "up" : value < 0 ? "down" : "flat";
  const arrow = direction === "up" ? "↑" : direction === "down" ? "↓" : "→";
  const improved =
    improvedWhen !== "neutral" &&
    ((improvedWhen === "up" && value > 0) || (improvedWhen === "down" && value < 0));
  const regressed =
    improvedWhen !== "neutral" &&
    ((improvedWhen === "up" && value < 0) || (improvedWhen === "down" && value > 0));

  return (
    <span
      className={`${styles.badge} ${
        improved ? styles.improved : regressed ? styles.regressed : styles.flat
      }`}
    >
      {arrow} {formatDelta(value, decimals, suffix)}
    </span>
  );
}
