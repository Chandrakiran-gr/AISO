"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import styles from "../dashboard.module.css";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type ActionData = {
  id: string;
  title: string;
  description: string | null;
  priority: string | null;
  category: string | null;
  impact_pts: string | null;
  effort: string | null;
  status: "open" | "done" | "dismissed" | string | null;
};

const STATUSES = ["open", "done", "dismissed"] as const;

export default function ActionsPage() {
  const [client, setClient] = useState<ClientData | null>(null);
  const [actions, setActions] = useState<ActionData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function updateStatus(actionId: string, status: (typeof STATUSES)[number]) {
    if (!client) return;
    const res = await fetch(`${API}/v1/clients/${client.id}/actions/${actionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) {
      setError("Unable to update action status");
      return;
    }
    const updated: ActionData = await res.json();
    setActions((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
  }

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error("Unable to load clients");
        const clients: ClientData[] = await clientsRes.json();
        const firstClient = clients[0] ?? null;
        if (!firstClient) {
          if (active) setLoading(false);
          return;
        }

        const actionsRes = await fetch(`${API}/v1/clients/${firstClient.id}/actions`, {
          cache: "no-store",
        });
        if (!actionsRes.ok) throw new Error("Unable to load actions");
        const actionRows: ActionData[] = await actionsRes.json();

        if (active) {
          setClient(firstClient);
          setActions(actionRows);
          setLoading(false);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Unable to load action plan");
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, []);

  const openCount = actions.filter((item) => item.status === "open").length;

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Action Plan</h1>
          <p className={styles.topCrumb}>
            {client ? `${client.name} · ${openCount} open actions` : "No business profile yet"}
          </p>
        </div>
        <Link href="/onboarding" className={styles.newScanBtn}>Run new scan</Link>
      </header>

      <main className={styles.content}>
        {loading && <div className={styles.previewBanner}>Loading action plan...</div>}
        {error && <div className={styles.previewBanner}>{error}</div>}
        {!loading && actions.length === 0 && (
          <div className={styles.previewBanner}>
            Complete a scan to generate data-backed recommendations.
          </div>
        )}

        <section className={styles.lowerGrid}>
          {actions.map((action) => (
            <article key={action.id} className={`${styles.card} ${styles.actionsCard}`}>
              <span className={styles.cardLabelTeal}>
                {action.priority ?? "medium"} · {action.category ?? "recommendation"}
              </span>
              <h2 className={styles.cardTitle}>{action.title}</h2>
              <p className={styles.heroSub}>{action.description}</p>
              <div className={styles.actionList}>
                <div className={styles.actionRow}>
                  <span>Impact</span>
                  <strong>{action.impact_pts ?? "Review"}</strong>
                </div>
                <div className={styles.actionRow}>
                  <span>Effort</span>
                  <strong>{action.effort ?? "TBD"}</strong>
                </div>
              </div>
              <div className={styles.actionControls}>
                {STATUSES.map((status) => (
                  <button
                    key={status}
                    type="button"
                    className={status === action.status ? styles.primaryButton : styles.secondaryButton}
                    onClick={() => void updateStatus(action.id, status)}
                  >
                    {status}
                  </button>
                ))}
              </div>
            </article>
          ))}
        </section>
      </main>
    </div>
  );
}
