"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { ActionData, GapReport, MetricsData } from "../DashboardOverview";
import ScanComparisonPanel from "@/components/ScanComparisonPanel";
import ScanSelector from "@/components/ScanSelector";
import type { ScanOption } from "@/components/ScanSelector";
import styles from "./compare.module.css";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type ScanBundle = {
  metrics: MetricsData | null;
  gapReport: GapReport | null;
  actions: ActionData[];
};

type CompareState = {
  client: ClientData | null;
  scans: ScanOption[];
  left: ScanBundle;
  right: ScanBundle;
  loading: boolean;
  dataLoading: boolean;
  error: string | null;
};

const EMPTY_BUNDLE: ScanBundle = {
  metrics: null,
  gapReport: null,
  actions: [],
};

function formatDate(value?: string | null): string {
  if (!value) return "No scans";
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

async function loadScanBundle(clientId: string, scanId: string): Promise<ScanBundle> {
  const encodedScanId = encodeURIComponent(scanId);
  const [metricsRes, gapReportRes, actionsRes] = await Promise.all([
    fetch(`${API}/v1/clients/${clientId}/metrics?scan_id=${encodedScanId}`, { cache: "no-store" }),
    fetch(`${API}/v1/clients/${clientId}/gap-report?scan_id=${encodedScanId}`, { cache: "no-store" }),
    fetch(`${API}/v1/clients/${clientId}/actions?scan_id=${encodedScanId}`, { cache: "no-store" }),
  ]);

  return {
    metrics: metricsRes.ok ? await metricsRes.json() : null,
    gapReport: gapReportRes.ok ? await gapReportRes.json() : null,
    actions: actionsRes.ok ? await actionsRes.json() : [],
  };
}

function CompareClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [selectedA, setSelectedA] = useState("");
  const [selectedB, setSelectedB] = useState("");
  const [state, setState] = useState<CompareState>({
    client: null,
    scans: [],
    left: EMPTY_BUNDLE,
    right: EMPTY_BUNDLE,
    loading: true,
    dataLoading: false,
    error: null,
  });

  useEffect(() => {
    let active = true;

    async function loadScans() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error("Unable to load clients");
        const clients: ClientData[] = await clientsRes.json();
        const firstClient = clients[0] ?? null;
        if (!firstClient) {
          if (active) {
            setState((prev) => ({ ...prev, client: null, scans: [], loading: false }));
          }
          return;
        }

        const scansRes = await fetch(`${API}/v1/clients/${firstClient.id}/scans`, { cache: "no-store" });
        if (!scansRes.ok) throw new Error("Unable to load scans");
        const scans: ScanOption[] = await scansRes.json();
        const scanIds = new Set(scans.map((scan) => scan.id));
        const queryA = searchParams.get("a");
        const queryB = searchParams.get("b");
        const validQueryA = queryA && scanIds.has(queryA) ? queryA : "";
        const validQueryB = queryB && scanIds.has(queryB) ? queryB : "";
        const defaultB = validQueryB || scans[0]?.id || "";
        const defaultA =
          validQueryA ||
          scans.find((scan) => scan.id !== defaultB)?.id ||
          scans[1]?.id ||
          defaultB;
        const nextA = defaultA;
        const nextB =
          validQueryB && validQueryB !== nextA
            ? validQueryB
            : scans.find((scan) => scan.id !== nextA)?.id || defaultB;

        if (active) {
          setSelectedA(nextA);
          setSelectedB(nextB);
          setState((prev) => ({
            ...prev,
            client: firstClient,
            scans,
            loading: false,
            error: null,
          }));
        }
      } catch (error) {
        if (active) {
          setState((prev) => ({
            ...prev,
            loading: false,
            error: error instanceof Error ? error.message : "Unable to load comparison",
          }));
        }
      }
    }

    void loadScans();
    return () => {
      active = false;
    };
  }, [searchParams]);

  useEffect(() => {
    if (!state.client || !selectedA || !selectedB || state.scans.length < 2) return;
    let active = true;

    async function loadComparisonData() {
      setState((prev) => ({ ...prev, dataLoading: true, error: null }));
      try {
        const [left, right] = await Promise.all([
          loadScanBundle(state.client!.id, selectedA),
          loadScanBundle(state.client!.id, selectedB),
        ]);
        if (active) {
          setState((prev) => ({
            ...prev,
            left,
            right,
            dataLoading: false,
            error: null,
          }));
        }
      } catch (error) {
        if (active) {
          setState((prev) => ({
            ...prev,
            dataLoading: false,
            error: error instanceof Error ? error.message : "Unable to load scan comparison",
          }));
        }
      }
    }

    void loadComparisonData();
    return () => {
      active = false;
    };
  }, [selectedA, selectedB, state.client, state.scans.length]);

  function updateSelection(nextA: string, nextB: string) {
    setSelectedA(nextA);
    setSelectedB(nextB);
    router.replace(`/dashboard/compare?a=${encodeURIComponent(nextA)}&b=${encodeURIComponent(nextB)}`, {
      scroll: false,
    });
  }

  const leftScan = useMemo(
    () => state.scans.find((scan) => scan.id === selectedA) ?? null,
    [selectedA, state.scans],
  );
  const rightScan = useMemo(
    () => state.scans.find((scan) => scan.id === selectedB) ?? null,
    [selectedB, state.scans],
  );

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Scan Comparison</h1>
          <p className={styles.topCrumb}>
            {state.client
              ? `${state.client.name} · ${formatDate(leftScan?.created_at)} vs ${formatDate(rightScan?.created_at)}`
              : "Compare scan performance over time"}
          </p>
        </div>
        <Link href="/dashboard/progress" className={styles.secondaryButton}>View progress</Link>
      </header>

      <main className={styles.content}>
        <section className={styles.hero}>
          <div>
            <h1>Compare before and after visibility scans</h1>
            <p>
              Select two scans to inspect score movement, gap changes, and recommendation follow-through.
            </p>
          </div>
        </section>

        {state.error && <div className={styles.notice}>{state.error}</div>}
        {state.loading && <div className={styles.notice}>Loading comparison data...</div>}

        {!state.loading && state.scans.length < 2 && (
          <section className={styles.emptyState}>
            <h2>{state.client ? "Run more scans to compare progress" : "Run your first scan"}</h2>
            <p>
              {state.client
                ? "AISO needs at least two scans before it can calculate before-and-after movement."
                : "Set up your profile and complete a scan before comparing visibility movement."}
            </p>
            <Link href="/onboarding" className={styles.primaryButton}>
              {state.client ? "Run new scan" : "Run first scan"}
            </Link>
          </section>
        )}

        {!state.loading && state.scans.length >= 2 && (
          <>
            <section className={styles.selectorCard} aria-label="Choose scans to compare">
              <ScanSelector
                id="scan-a"
                label="Scan A"
                value={selectedA}
                scans={state.scans}
                onChange={(scanId) => updateSelection(scanId, selectedB)}
              />
              <ScanSelector
                id="scan-b"
                label="Scan B"
                value={selectedB}
                scans={state.scans}
                onChange={(scanId) => updateSelection(selectedA, scanId)}
              />
            </section>

            {state.dataLoading ? (
              <div className={styles.notice}>Loading selected scans...</div>
            ) : (
              <ScanComparisonPanel
                left={{ scan: leftScan, ...state.left }}
                right={{ scan: rightScan, ...state.right }}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className={styles.notice}>Loading comparison...</div>}>
      <CompareClient />
    </Suspense>
  );
}
