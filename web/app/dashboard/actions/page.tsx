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
  scan_id: string | null;
  action_key: string | null;
  title: string;
  description: string | null;
  priority: string | null;
  category: string | null;
  impact_pts: string | null;
  effort: string | null;
  score: number | null;
  sort_order: number | null;
  evidence_json: string | null;
  status: "open" | "done" | "dismissed" | string | null;
};

const STATUSES = ["open", "done", "dismissed"] as const;
const STATUS_LABELS: Record<(typeof STATUSES)[number], string> = {
  open: "To do",
  done: "Done",
  dismissed: "Dismiss",
};
const STATUS_BADGE_LABELS: Record<(typeof STATUSES)[number], string> = {
  open: "Open",
  done: "Done",
  dismissed: "Dismissed",
};

type Evidence = {
  kind?: string;
  provider_label?: string;
  group?: string;
  group_label?: string;
  score?: number;
  overall_score?: number;
  competitor?: string;
  citation_count?: number;
  unique_source_domains?: number;
  total_questions?: number;
};

function parseEvidence(action: ActionData): Evidence {
  if (!action.evidence_json) return {};
  try {
    const parsed = JSON.parse(action.evidence_json);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function evidenceChips(action: ActionData): string[] {
  const evidence = parseEvidence(action);
  const chips: string[] = [];

  if (evidence.provider_label) chips.push(evidence.provider_label);
  if (evidence.group) chips.push(`${evidence.group}${evidence.group_label ? ` · ${evidence.group_label}` : ""}`);
  if (typeof evidence.score === "number") chips.push(`${Math.round(evidence.score)}/100 score`);
  if (typeof evidence.overall_score === "number") chips.push(`${Math.round(evidence.overall_score)}/100 overall`);
  if (evidence.competitor) chips.push(`vs ${evidence.competitor}`);
  if (typeof evidence.citation_count === "number") chips.push(`${evidence.citation_count} citations`);
  if (typeof evidence.unique_source_domains === "number") chips.push(`${evidence.unique_source_domains} source domains`);
  if (typeof evidence.total_questions === "number") chips.push(`${evidence.total_questions} results`);

  return chips.slice(0, 4);
}

function actionStatus(action: ActionData): (typeof STATUSES)[number] {
  return action.status === "done" || action.status === "dismissed" ? action.status : "open";
}

function priorityLabel(priority: string | null): string {
  if (!priority) return "Medium";
  return `${priority.charAt(0).toUpperCase()}${priority.slice(1)}`;
}

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

  const openCount = actions.filter((item) => actionStatus(item) === "open").length;
  const highCount = actions.filter((item) => actionStatus(item) === "open" && item.priority === "high").length;
  const doneCount = actions.filter((item) => item.status === "done").length;
  const dismissedCount = actions.filter((item) => item.status === "dismissed").length;
  const openActions = actions.filter((item) => actionStatus(item) === "open");
  const closedActions = actions.filter((item) => actionStatus(item) !== "open");

  function renderActionCard(action: ActionData) {
    const chips = evidenceChips(action);
    const currentStatus = actionStatus(action);
    return (
      <article key={action.id} className={styles.actionPlanCard}>
        <div className={styles.actionPlanHeader}>
          <span className={`${styles.priorityBadge} ${styles[`priority${priorityLabel(action.priority)}`]}`}>
            {priorityLabel(action.priority)}
          </span>
          <span className={styles.statusBadgeAction}>{STATUS_BADGE_LABELS[currentStatus]}</span>
        </div>
        <h2 className={styles.actionPlanTitle}>{action.title}</h2>
        <p className={styles.actionPlanDescription}>{action.description}</p>
        {chips.length > 0 && (
          <div className={styles.evidenceChips}>
            {chips.map((chip) => (
              <span key={chip} className={styles.evidenceChip}>{chip}</span>
            ))}
          </div>
        )}
        <div className={styles.actionMetaGrid}>
          <span>
            <small>Impact</small>
            <strong>{action.impact_pts ?? "Review"}</strong>
          </span>
          <span>
            <small>Effort</small>
            <strong>{action.effort ?? "TBD"}</strong>
          </span>
          <span>
            <small>Category</small>
            <strong>{action.category ?? "recommendation"}</strong>
          </span>
        </div>
        <div className={styles.actionStatusControls}>
          {STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              className={status === currentStatus ? styles.statusButtonActive : styles.statusButton}
              onClick={() => void updateStatus(action.id, status)}
            >
              {STATUS_LABELS[status]}
            </button>
          ))}
        </div>
      </article>
    );
  }

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

        {actions.length > 0 && (
          <section className={styles.actionStatsGrid} aria-label="Action plan summary">
            <div className={styles.actionStatCard}>
              <span>{openCount}</span>
              <strong>Open actions</strong>
            </div>
            <div className={styles.actionStatCard}>
              <span>{highCount}</span>
              <strong>High priority</strong>
            </div>
            <div className={styles.actionStatCard}>
              <span>{doneCount}</span>
              <strong>Completed</strong>
            </div>
            <div className={styles.actionStatCard}>
              <span>{dismissedCount}</span>
              <strong>Dismissed</strong>
            </div>
          </section>
        )}

        <section className={styles.actionWorkspace}>
          {openActions.length > 0 && (
            <div className={styles.actionSection}>
              <div className={styles.actionSectionHeader}>
                <h2>Current priorities</h2>
                <span>{openActions.length} to review</span>
              </div>
              <div className={styles.actionPlanGrid}>
                {openActions.map(renderActionCard)}
              </div>
            </div>
          )}

          {closedActions.length > 0 && (
            <div className={styles.actionSection}>
              <div className={styles.actionSectionHeader}>
                <h2>Completed and dismissed</h2>
                <span>{closedActions.length} archived</span>
              </div>
              <div className={styles.actionPlanGrid}>
                {closedActions.map(renderActionCard)}
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
