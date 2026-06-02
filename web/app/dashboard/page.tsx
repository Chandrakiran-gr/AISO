"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  DashboardOverview,
  type ActionData,
  type GapReport,
  type MetricsData,
} from "./DashboardOverview";
import styles from "./dashboard.module.css";

export const dynamic = "force-dynamic";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type ScanData = {
  id: string;
  status: string;
  providers: string[] | null;
  groups: string[] | null;
  skipped_providers?: string[] | null;
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
};

type ClientScanBundle = {
  client: ClientData;
  scans: ScanData[];
};

type DashboardState = {
  client: ClientData | null;
  scans: ScanData[];
  metrics: MetricsData | null;
  gapReport: GapReport | null;
  actions: ActionData[];
  loading: boolean;
  error: string | null;
};

function formatDate(value?: string | null): string {
  if (!value) return "No completed scans";
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function DashboardPage() {
  const [state, setState] = useState<DashboardState>({
    client: null,
    scans: [],
    metrics: null,
    gapReport: null,
    actions: [],
    loading: true,
    error: null,
  });

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error("Unable to load clients");

        const clients: ClientData[] = await clientsRes.json();
        if (!clients.length) {
          if (active) {
            setState((prev) => ({ ...prev, client: null, loading: false }));
          }
          return;
        }

        const bundles: ClientScanBundle[] = await Promise.all(
          clients.map(async (item) => {
            const scansRes = await fetch(`${API}/v1/clients/${item.id}/scans`, { cache: "no-store" });
            if (!scansRes.ok) throw new Error("Unable to load scans");
            const scans: ScanData[] = await scansRes.json();
            return { client: item, scans };
          }),
        );
        const newestBundle = bundles.reduce<ClientScanBundle | null>((best, current) => {
          if (!current.scans.length) return best;
          if (!best || !best.scans.length) return current;
          const currentTime = Date.parse(current.scans[0]?.created_at ?? "");
          const bestTime = Date.parse(best.scans[0]?.created_at ?? "");
          return currentTime > bestTime ? current : best;
        }, null);
        const selectedBundle = newestBundle ?? bundles[0];
        const client = selectedBundle.client;
        const scans = selectedBundle.scans;
        const latestComplete = scans.find((scan) => scan.status === "complete") ?? scans[0] ?? null;
        const [metricsRes, actionsRes, gapReportRes] = await Promise.all([
          fetch(`${API}/v1/clients/${client.id}/metrics`, { cache: "no-store" }),
          fetch(`${API}/v1/clients/${client.id}/actions?status=open`, { cache: "no-store" }),
          latestComplete
            ? fetch(`${API}/v1/clients/${client.id}/gap-report?scan_id=${latestComplete.id}`, { cache: "no-store" })
            : Promise.resolve(null),
        ]);

        const metrics: MetricsData | null = metricsRes.ok ? await metricsRes.json() : null;
        const actions: ActionData[] = actionsRes.ok ? await actionsRes.json() : [];
        const gapReport: GapReport | null = gapReportRes && gapReportRes.ok ? await gapReportRes.json() : null;

        if (active) {
          setState({
            client,
            scans,
            metrics,
            gapReport,
            actions,
            loading: false,
            error: null,
          });
        }
      } catch (error) {
        if (active) {
          setState((prev) => ({
            ...prev,
            loading: false,
            error: error instanceof Error ? error.message : "Unable to load dashboard",
          }));
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, []);

  const latestScan = state.scans[0] ?? null;
  const scanRunning = latestScan?.status === "running" || latestScan?.status === "pending";
  const failedScan = latestScan?.status === "failed" ? latestScan : null;
  const showOnboardingRecommendation = !state.loading && !state.error && !state.metrics && state.scans.length === 0;
  const scanMetaLabel = `Latest scan: ${latestScan ? latestScan.status : "none"}${
    latestScan?.providers?.length ? ` · ${latestScan.providers.length} platforms` : ""
  }`;

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Dashboard</h1>
          <p className={styles.topCrumb}>
            {state.loading
              ? "Loading..."
              : showOnboardingRecommendation
                ? state.client
                  ? `Complete onboarding for ${state.client.name}`
                  : "Complete onboarding to create your workspace"
              : state.client
                ? `${state.client.name} · ${formatDate(latestScan?.completed_at ?? latestScan?.created_at)}`
                : "Create your first business profile"}
          </p>
        </div>
        <div className={styles.topActions}>
          <Link href="/onboarding" className={styles.newScanBtn}>
            {showOnboardingRecommendation ? "Complete onboarding" : "Run new scan"}
          </Link>
        </div>
      </header>

      <main className={styles.content}>
        <section className={styles.commandHeader}>
          <div className={styles.commandHeaderCopy}>
            <span className={styles.commandEyebrow}>Overview</span>
            <h2 className={styles.commandTitle}>
              {showOnboardingRecommendation
                ? state.client
                  ? `Finish setting up ${state.client.name}`
                  : "Set up your first AI visibility scan"
              : state.client
                ? `What AI is saying about ${state.client.name}`
                : "Set up your first AI visibility scan"}
            </h2>
            <p className={styles.commandSub}>
              {state.metrics
                ? `${state.metrics.total_questions} provider-question results analyzed from the latest completed scan.`
                : "Complete onboarding to review your business context, launch the first scan, and unlock visibility insights."}
            </p>
          </div>
          <div className={styles.commandActions}>
            <span>{scanMetaLabel}</span>
            <Link href="/onboarding" className={styles.newScanBtn}>
              {state.client && state.scans.length > 0 ? "Run new scan" : "Complete onboarding"}
            </Link>
          </div>
        </section>

        {state.error && <div className={styles.previewBanner}>{state.error}</div>}

        {showOnboardingRecommendation && (
          <section className={styles.onboardingPrompt} aria-labelledby="onboarding-prompt-heading">
            <div>
              <span className={styles.cardLabelTeal}>Recommended setup</span>
              <h2 id="onboarding-prompt-heading">
                {state.client ? `Finish onboarding for ${state.client.name}` : "Complete onboarding to unlock your dashboard"}
              </h2>
              <p>
                Add the business website, review the context AISO discovers, choose providers, and run the first scan so this dashboard has real metrics to work from.
              </p>
              <div className={styles.onboardingSteps} aria-label="Onboarding steps">
                <span>Business profile</span>
                <span>Context review</span>
                <span>First visibility scan</span>
              </div>
            </div>
            <Link href="/onboarding" className={styles.newScanBtn}>Complete onboarding</Link>
          </section>
        )}

        {scanRunning && (
          <div className={styles.scanBanner}>
            <span className={styles.scanBannerSpinner} aria-hidden="true" />
            <p>
              <strong>Scan in progress</strong> — querying AI platforms across the selected question set.
            </p>
          </div>
        )}

        {failedScan && (
          <div className={styles.previewBanner}>
            Latest scan failed: {failedScan.error || "Check provider keys and try again."}
          </div>
        )}

        {!showOnboardingRecommendation && !state.loading && state.client && !state.metrics && !scanRunning && !failedScan && (
          <div className={styles.previewBanner}>
            No completed scan metrics yet. Run your first scan to populate the dashboard.
          </div>
        )}

        {!showOnboardingRecommendation && (
          <DashboardOverview
            clientName={state.client?.name}
            metrics={state.metrics}
            gapReport={state.gapReport}
            actions={state.actions}
            scanMetaLabel={scanMetaLabel}
          />
        )}
      </main>
    </div>
  );
}
