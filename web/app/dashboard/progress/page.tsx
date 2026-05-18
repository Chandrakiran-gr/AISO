"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ProgressTrendChart, { type TrendPoint } from "@/components/ProgressTrendChart";
import styles from "./progress.module.css";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type TimelineMetrics = {
  overall_score: number;
  total_questions: number;
  mention_count: number;
  gap_count: number;
  action_count: number;
  completed_action_count: number;
  action_completion_rate: number;
};

type TimelinePoint = {
  client_id: string;
  client_name: string;
  scan_id: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  metrics: TimelineMetrics;
};

type ProgressState = {
  client: ClientData | null;
  points: TimelinePoint[];
  loading: boolean;
  error: string | null;
};

function formatAxisDate(value: string): string {
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function formatLongDate(value?: string | null): string {
  if (!value) return "No completed scans";
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function toTrendPoint(point: TimelinePoint, value: number): TrendPoint {
  return {
    scanId: point.scan_id,
    label: formatAxisDate(point.completed_at ?? point.created_at),
    value,
  };
}

export default function ProgressPage() {
  const router = useRouter();
  const [state, setState] = useState<ProgressState>({
    client: null,
    points: [],
    loading: true,
    error: null,
  });

  useEffect(() => {
    let active = true;

    async function loadProgress() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error("Unable to load clients");
        const clients: ClientData[] = await clientsRes.json();
        const firstClient = clients[0] ?? null;

        if (!firstClient) {
          if (active) {
            setState({ client: null, points: [], loading: false, error: null });
          }
          return;
        }

        const timelineRes = await fetch(
          `${API}/v1/scans/metrics/timeline?client_id=${encodeURIComponent(firstClient.id)}`,
          { cache: "no-store" },
        );
        if (!timelineRes.ok) throw new Error("Unable to load progress timeline");
        const points: TimelinePoint[] = await timelineRes.json();

        if (active) {
          setState({
            client: firstClient,
            points,
            loading: false,
            error: null,
          });
        }
      } catch (error) {
        if (active) {
          setState((prev) => ({
            ...prev,
            loading: false,
            error: error instanceof Error ? error.message : "Unable to load progress",
          }));
        }
      }
    }

    void loadProgress();
    return () => {
      active = false;
    };
  }, []);

  const orderedPoints = useMemo(
    () =>
      state.points
        .slice()
        .sort(
          (a, b) =>
            new Date(a.completed_at ?? a.created_at).getTime() -
            new Date(b.completed_at ?? b.created_at).getTime(),
        ),
    [state.points],
  );

  const firstGapCount = orderedPoints[0]?.metrics.gap_count ?? 0;
  const visibilityData = orderedPoints.map((point) =>
    toTrendPoint(point, Number(point.metrics.overall_score.toFixed(1))),
  );
  const gapsClosedData = orderedPoints.map((point) =>
    toTrendPoint(point, Math.max(firstGapCount - point.metrics.gap_count, 0)),
  );
  const completionRateData = orderedPoints.map((point) =>
    toTrendPoint(point, Number(point.metrics.action_completion_rate.toFixed(1))),
  );

  function openScan(scanId: string) {
    router.push(`/dashboard/scans/${scanId}`);
  }

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Progress</h1>
          <p className={styles.topCrumb}>
            {state.client
              ? `${state.client.name} · ${orderedPoints.length} completed scans`
              : "Track scan movement over time"}
          </p>
        </div>
        <div className={styles.topActions}>
          <Link href="/dashboard/compare" className={styles.secondaryButton}>
            Compare scans
          </Link>
          <Link href="/onboarding" className={styles.primaryButton}>
            New scan
          </Link>
        </div>
      </header>

      <main className={styles.content}>
        <section className={styles.hero}>
          <div>
            <h1>AI visibility progress over time</h1>
            <p>
              See how visibility score, open gaps, and recommendation follow-through move across completed scans.
            </p>
          </div>
          {!!orderedPoints.length && (
            <div className={styles.rangeBadge}>
              <span>Range</span>
              <strong>
                {formatLongDate(orderedPoints[0]?.completed_at ?? orderedPoints[0]?.created_at)} -{" "}
                {formatLongDate(
                  orderedPoints[orderedPoints.length - 1]?.completed_at ??
                    orderedPoints[orderedPoints.length - 1]?.created_at,
                )}
              </strong>
            </div>
          )}
        </section>

        {state.error && <div className={styles.notice}>{state.error}</div>}
        {state.loading && <div className={styles.notice}>Loading progress...</div>}

        {!state.loading && !state.error && orderedPoints.length === 0 && (
          <section className={styles.emptyState}>
            <h2>No completed scans yet</h2>
            <p>Run your first scan to start building a progress timeline.</p>
            <Link href="/onboarding" className={styles.primaryButton}>
              Run first scan
            </Link>
          </section>
        )}

        {!state.loading && !state.error && orderedPoints.length === 1 && (
          <section className={styles.emptyState}>
            <h2>Run more scans to track your progress over time</h2>
            <p>Progress trends need at least two completed scans for this account.</p>
            <div className={styles.emptyActions}>
              <Link href={`/dashboard/scans/${orderedPoints[0].scan_id}`} className={styles.secondaryButton}>
                View current scan
              </Link>
              <Link href="/onboarding" className={styles.primaryButton}>
                Run new scan
              </Link>
            </div>
          </section>
        )}

        {!state.loading && !state.error && orderedPoints.length >= 2 && (
          <section className={styles.chartStack} aria-label="Progress trend charts">
            <ProgressTrendChart
              title="AI Visibility Score over time"
              description="Score movement across completed scans."
              data={visibilityData}
              stroke="var(--accent-teal)"
              variant="primary"
              onPointClick={openScan}
            />
            <div className={styles.secondaryGrid}>
              <ProgressTrendChart
                title="Gaps Closed over time"
                description="Closed gap count measured against the first scan in this timeline."
                data={gapsClosedData}
                stroke="var(--accent-warning)"
                onPointClick={openScan}
              />
              <ProgressTrendChart
                title="Recommendations Completion Rate over time"
                description="Completed recommendations as a share of recommendations created for each scan."
                data={completionRateData}
                valueSuffix="%"
                stroke="var(--accent-violet)"
                onPointClick={openScan}
              />
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
