"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
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
};

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
  onPointClick,
}: {
  title: string;
  description: string;
  data: TrendPoint[];
  valueSuffix?: string;
  stroke?: string;
  variant?: "default" | "primary";
  onPointClick: (scanId: string) => void;
}) {
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
    </section>
  );
}
