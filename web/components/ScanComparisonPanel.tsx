"use client";

import type { ActionData, GapReport, MetricsData } from "@/app/dashboard/DashboardOverview";
import MetricDeltaBadge from "./MetricDeltaBadge";
import styles from "./ScanComparisonPanel.module.css";

type ScanOption = {
  id: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
};

type ScanBundle = {
  scan: ScanOption | null;
  metrics: MetricsData | null;
  gapReport: GapReport | null;
  actions: ActionData[];
};

type Row = {
  label: string;
  a: number;
  b: number;
  suffix?: string;
  decimals?: number;
  improvedWhen?: "up" | "down" | "neutral";
};

function formatDate(value?: string | null): string {
  if (!value) return "Not selected";
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatValue(value: number, suffix = "", decimals = 0): string {
  return `${value.toLocaleString("en-US", {
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals > 0 ? decimals : 0,
  })}${suffix}`;
}

function ownMentionCount(metrics: MetricsData | null): number {
  return metrics?.competitors.find((competitor) => competitor.is_you)?.mention_count ?? 0;
}

function missedGapKeys(report: GapReport | null): Set<string> {
  return new Set(
    (report?.query_results ?? [])
      .filter((query) => !query.appeared)
      .map((query) => `${query.provider}::${query.group}::${query.question}`),
  );
}

function totalGaps(report: GapReport | null): number {
  const summary = report as (GapReport & { summary?: { missed_count?: number } }) | null;
  return summary?.summary?.missed_count ?? missedGapKeys(report).size;
}

function actionStats(actions: ActionData[]) {
  const total = actions.length;
  const completed = actions.filter((action) => action.status === "done").length;
  return {
    total,
    completed,
    completionRate: total ? Math.round((completed / total) * 1000) / 10 : 0,
  };
}

function MetricRow({ row }: { row: Row }) {
  return (
    <div className={styles.metricRow}>
      <span className={styles.metricLabel}>{row.label}</span>
      <strong>{formatValue(row.a, row.suffix, row.decimals)}</strong>
      <strong>{formatValue(row.b, row.suffix, row.decimals)}</strong>
      <MetricDeltaBadge
        value={row.b - row.a}
        suffix={row.suffix}
        decimals={row.decimals}
        improvedWhen={row.improvedWhen}
      />
    </div>
  );
}

function ScanHeader({ title, bundle }: { title: string; bundle: ScanBundle }) {
  return (
    <div className={styles.scanHeader}>
      <span>{title}</span>
      <strong>{formatDate(bundle.scan?.completed_at ?? bundle.scan?.created_at)}</strong>
      <small>{bundle.scan?.status ?? "No scan selected"}</small>
    </div>
  );
}

export default function ScanComparisonPanel({
  left,
  right,
}: {
  left: ScanBundle;
  right: ScanBundle;
}) {
  const leftGaps = missedGapKeys(left.gapReport);
  const rightGaps = missedGapKeys(right.gapReport);
  const newGaps = [...rightGaps].filter((key) => !leftGaps.has(key)).length;
  const closedGaps = [...leftGaps].filter((key) => !rightGaps.has(key)).length;
  const leftActions = actionStats(left.actions);
  const rightActions = actionStats(right.actions);

  const metricRows: Row[] = [
    {
      label: "AI Visibility Score",
      a: left.metrics?.overall_score ?? 0,
      b: right.metrics?.overall_score ?? 0,
      decimals: 1,
      improvedWhen: "up",
    },
    {
      label: "Provider-question results",
      a: left.metrics?.total_questions ?? 0,
      b: right.metrics?.total_questions ?? 0,
      improvedWhen: "neutral",
    },
    {
      label: "Brand mentions",
      a: ownMentionCount(left.metrics),
      b: ownMentionCount(right.metrics),
      improvedWhen: "up",
    },
    {
      label: "Intent groups measured",
      a: left.metrics?.group_metrics.length ?? 0,
      b: right.metrics?.group_metrics.length ?? 0,
      improvedWhen: "neutral",
    },
  ];

  const gapRows: Row[] = [
    {
      label: "Total gaps",
      a: totalGaps(left.gapReport),
      b: totalGaps(right.gapReport),
      improvedWhen: "down",
    },
    {
      label: "New gaps introduced",
      a: 0,
      b: newGaps,
      improvedWhen: "down",
    },
    {
      label: "Gaps closed",
      a: 0,
      b: closedGaps,
      improvedWhen: "up",
    },
  ];

  const actionRows: Row[] = [
    {
      label: "Total recommendations",
      a: leftActions.total,
      b: rightActions.total,
      improvedWhen: "down",
    },
    {
      label: "Completed recommendations",
      a: leftActions.completed,
      b: rightActions.completed,
      improvedWhen: "up",
    },
    {
      label: "Completion rate",
      a: leftActions.completionRate,
      b: rightActions.completionRate,
      suffix: "%",
      decimals: 1,
      improvedWhen: "up",
    },
  ];

  return (
    <section className={styles.panel} aria-label="Scan comparison">
      <div className={styles.scanHeaders}>
        <ScanHeader title="Scan A" bundle={left} />
        <ScanHeader title="Scan B" bundle={right} />
      </div>

      <div className={styles.tableHeader}>
        <span>Metric</span>
        <span>Scan A</span>
        <span>Scan B</span>
        <span>Change</span>
      </div>

      <div className={styles.section}>
        <h2>Metrics</h2>
        {metricRows.map((row) => <MetricRow key={row.label} row={row} />)}
      </div>

      <div className={styles.section}>
        <h2>Gap report summary</h2>
        {gapRows.map((row) => <MetricRow key={row.label} row={row} />)}
      </div>

      <div className={styles.section}>
        <h2>Actions</h2>
        {actionRows.map((row) => <MetricRow key={row.label} row={row} />)}
      </div>
    </section>
  );
}
