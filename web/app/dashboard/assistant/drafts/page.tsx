"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import ContentDraftCard, { ContentDraftData } from "@/components/ContentDraftCard/ContentDraftCard";
import styles from "./drafts.module.css";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type DraftPatch = {
  title?: string;
  content?: string;
  review_notes?: string | null;
};

const STATUS_ORDER = ["pending_review", "approved", "rejected", "archived"] as const;
const STATUS_LABELS: Record<string, string> = {
  pending_review: "Pending review",
  approved: "Approved",
  rejected: "Rejected",
  archived: "Archived",
};

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.detail === "string") return data.detail;
  } catch {
    // Keep fallback.
  }
  return fallback;
}

export default function ContentDraftsPage() {
  const [client, setClient] = useState<ClientData | null>(null);
  const [drafts, setDrafts] = useState<ContentDraftData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error(await readError(clientsRes, "Unable to load clients"));
        const clients: ClientData[] = await clientsRes.json();
        const firstClient = clients[0] ?? null;
        if (!firstClient) {
          if (active) setLoading(false);
          return;
        }

        const draftsRes = await fetch(
          `${API}/v1/assistant/content-drafts?client_id=${encodeURIComponent(firstClient.id)}`,
          { cache: "no-store" },
        );
        if (!draftsRes.ok) throw new Error(await readError(draftsRes, "Unable to load content drafts"));
        const draftRows: ContentDraftData[] = await draftsRes.json();

        if (active) {
          setClient(firstClient);
          setDrafts(draftRows);
          setLoading(false);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Unable to load content drafts");
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, []);

  const grouped = useMemo(() => {
    return STATUS_ORDER.reduce<Record<string, ContentDraftData[]>>((acc, status) => {
      acc[status] = drafts.filter((draft) => draft.status === status);
      return acc;
    }, {} as Record<string, ContentDraftData[]>);
  }, [drafts]);

  function replaceDraft(updated: ContentDraftData) {
    setDrafts((prev) => prev.map((draft) => (draft.id === updated.id ? updated : draft)));
    return updated;
  }

  async function patchDraft(path: string, payload?: DraftPatch): Promise<ContentDraftData> {
    const response = await fetch(`${API}/v1/assistant/content-drafts/${path}`, {
      method: "PATCH",
      headers: payload ? { "Content-Type": "application/json" } : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (!response.ok) throw new Error(await readError(response, "Unable to update content draft"));
    return replaceDraft(await response.json());
  }

  const counts = STATUS_ORDER.map((status) => ({
    status,
    count: grouped[status]?.length ?? 0,
  }));

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Content Library</h1>
          <p className={styles.topCrumb}>
            {client ? `${client.name} · ${drafts.length} drafts` : "No business profile yet"}
          </p>
        </div>
        <div className={styles.topActions}>
          <Link href="/dashboard/assistant" className={styles.secondaryButton}>
            Assistant
          </Link>
          <Link href="/dashboard/actions" className={styles.primaryButton}>
            Action plan
          </Link>
        </div>
      </header>

      <main className={styles.content}>
        <section className={styles.hero}>
          <div>
            <h1>Review, edit, and approve generated content</h1>
            <p>Drafts stay in AISO until a human approves, rejects, archives, or copies the final text.</p>
          </div>
          {client && <span className={styles.clientPill}>{client.name}</span>}
        </section>

        {loading && <div className={styles.notice}>Loading content drafts...</div>}
        {error && <div className={styles.notice}>{error}</div>}

        {!loading && !client && (
          <section className={styles.emptyState}>
            <h2>No business profile yet</h2>
            <p>Create a business profile before generating content drafts.</p>
            <Link href="/onboarding" className={styles.primaryButton}>
              Start onboarding
            </Link>
          </section>
        )}

        {client && (
          <>
            <section className={styles.statsGrid} aria-label="Content draft summary">
              {counts.map((item) => (
                <div key={item.status} className={styles.statCard}>
                  <span>{item.count}</span>
                  <strong>{STATUS_LABELS[item.status]}</strong>
                </div>
              ))}
            </section>

            <section className={styles.draftSections}>
              {STATUS_ORDER.map((status) => {
                const rows = grouped[status] ?? [];
                return (
                  <div key={status} className={styles.draftSection}>
                    <div className={styles.sectionHeader}>
                      <h2>{STATUS_LABELS[status]}</h2>
                      <span>{rows.length} visible</span>
                    </div>
                    {rows.length > 0 ? (
                      <div className={styles.draftGrid}>
                        {rows.map((draft) => (
                          <ContentDraftCard
                            key={`${draft.id}-${draft.updated_at}-${draft.status}`}
                            draft={draft}
                            onSave={(draftId, payload) => patchDraft(draftId, payload)}
                            onApprove={(draftId, payload) => patchDraft(`${draftId}/approve`, payload)}
                            onReject={(draftId, payload) => patchDraft(`${draftId}/reject`, payload)}
                            onArchive={(draftId) => patchDraft(`${draftId}/archive`)}
                          />
                        ))}
                      </div>
                    ) : (
                      <div className={styles.sectionEmpty}>No {STATUS_LABELS[status].toLowerCase()} drafts.</div>
                    )}
                  </div>
                );
              })}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
