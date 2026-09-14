"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import styles from "./ProgressTrendChart.module.css";

export type TrendPoint = {
  scanId: string;
  label: string;
  value: number;
  /** Which question set produced the score. Values are not comparable across a change. */
  methodology: string;
};

/**
 * First point measured by a different question set than the point before it.
 *
 * The retired G1-G7 bank included a direct-brand group that scored near 100%
 * by construction, so a switch to the onboarding prompt set drops the score
 * without visibility having moved. The chart marks that seam rather than
 * drawing it as a trend.
 */
function methodologyBreak(data: TrendPoint[]): TrendPoint | null {
  for (let i = 1; i < data.length; i += 1) {
    if (data[i].methodology !== data[i - 1].methodology) return data[i];
  }
  return null;
}

function payloadFromChartEvent(state: unknown): TrendPoint | null {
  const activePayload = (state as { activePayload?: { payload?: TrendPoint }[] } | null)?.activePayload;
  return activePayload?.[0]?.payload ?? null;
}

export default function ProgressTrendChart({
  title,
  description,
  data,
  valueSuffix = "",
  stroke = "var(--accent-teal)",
  variant = "default",
  markMethodologyBreak = true,
  onPointClick,
}: {
  title: string;
  description: string;
  data: TrendPoint[];
  valueSuffix?: string;
  stroke?: string;
  variant?: "default" | "primary";
  /** Off for series that are not derived from the scan's question set. */
  markMethodologyBreak?: boolean;
  onPointClick: (scanId: string) => void;
}) {
  const breakPoint = markMethodologyBreak ? methodologyBreak(data) : null;

  return (
    <section className={`${styles.card} ${variant === "primary" ? styles.primary : ""}`} aria-label={title}>
      <div className={styles.header}>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <span>{data.length} scans</span>
      </div>
      <div className={styles.chartFrame}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 12, right: 18, bottom: 8, left: 4 }}
            onClick={(state) => {
              const payload = payloadFromChartEvent(state);
              if (payload) onPointClick(payload.scanId);
            }}
          >
            <CartesianGrid stroke="var(--bg-hover)" strokeDasharray="4 8" />
            <XAxis
              dataKey="label"
              axisLine={false}
              tickLine={false}
              stroke="var(--text-muted)"
              tick={{ fill: "var(--text-muted)", fontSize: 12, fontWeight: 700 }}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              stroke="var(--text-muted)"
              tick={{ fill: "var(--text-muted)", fontSize: 12, fontWeight: 700 }}
              width={44}
              tickFormatter={(value) => `${value}${valueSuffix}`}
            />
            <Tooltip
              cursor={{ stroke: "var(--bg-hover)", strokeWidth: 1 }}
              formatter={(value) => [`${Number(value).toFixed(1)}${valueSuffix}`, title]}
              labelStyle={{ color: "var(--text-primary)", fontWeight: 800 }}
              contentStyle={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--bg-hover)",
                borderRadius: 12,
                color: "var(--text-primary)",
              }}
            />
            {breakPoint && (
              <ReferenceLine
                x={breakPoint.label}
                stroke="var(--text-muted)"
                strokeDasharray="3 5"
                strokeWidth={1}
                label={{
                  value: "New prompt set",
                  position: "insideTopRight",
                  fill: "var(--text-muted)",
                  fontSize: 11,
                  fontWeight: 800,
                }}
              />
            )}
            <Line
              type="monotone"
              dataKey="value"
              stroke={stroke}
              strokeWidth={3}
              dot={{ r: 5, strokeWidth: 2, fill: "var(--bg-deep)", stroke }}
              activeDot={{ r: 7, strokeWidth: 2, fill: "var(--bg-deep)", stroke }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {breakPoint && (
        <p className={styles.methodologyNote}>
          Scans before {breakPoint.label} measured a different set of questions,
          including brand-name prompts that almost always matched. Scores either
          side of this line are not directly comparable.
        </p>
      )}
    </section>
  );
}
