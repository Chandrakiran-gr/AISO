"use client";

import { useState } from "react";
import styles from "./ContentDraftCard.module.css";

export type ContentDraftData = {
  id: string;
  conversation_id: string | null;
  client_id: string;
  created_by: string;
  content_type: string;
  title: string;
  content: string;
  status: "pending_review" | "approved" | "rejected" | "archived" | string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  created_at: string;
  updated_at: string;
};

type DraftPatch = {
  title?: string;
  content?: string;
  review_notes?: string | null;
};

type Props = {
  draft: ContentDraftData;
  onSave: (draftId: string, payload: DraftPatch) => Promise<ContentDraftData>;
  onApprove: (draftId: string, payload: DraftPatch) => Promise<ContentDraftData>;
  onReject: (draftId: string, payload: DraftPatch) => Promise<ContentDraftData>;
  onArchive: (draftId: string) => Promise<ContentDraftData>;
};

const TYPE_LABELS: Record<string, string> = {
  blog_post: "Blog post",
  linkedin_post: "LinkedIn post",
  platform_listing: "Platform listing",
  review_response: "Review response",
  other: "Content",
};

const STATUS_LABELS: Record<string, string> = {
  pending_review: "Pending review",
  approved: "Approved",
  rejected: "Rejected",
  archived: "Archived",
};

function formatDate(value: string | null): string {
  if (!value) return "Not reviewed";
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function ContentDraftCard({
  draft,
  onSave,
  onApprove,
  onReject,
  onArchive,
}: Props) {
  const [title, setTitle] = useState(draft.title);
  const [content, setContent] = useState(draft.content);
  const [notes, setNotes] = useState(draft.review_notes ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function runAction(
    label: string,
    action: () => Promise<ContentDraftData>,
  ) {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update draft");
    } finally {
      setBusy(null);
    }
  }

  async function copyContent() {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }

  const payload = {
    title,
    content,
    review_notes: notes.trim() || null,
  };
  const isArchived = draft.status === "archived";
  const isApproved = draft.status === "approved";

  return (
    <article className={`${styles.card} ${styles[`status_${draft.status}`] ?? ""}`}>
      <header className={styles.header}>
        <div>
          <span className={styles.typePill}>{TYPE_LABELS[draft.content_type] ?? "Content"}</span>
          <h3>{draft.title}</h3>
        </div>
        <span className={styles.statusPill}>{STATUS_LABELS[draft.status] ?? draft.status}</span>
      </header>

      <label className={styles.field}>
        <span>Title</span>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          disabled={isArchived}
          maxLength={160}
        />
      </label>

      <label className={styles.field}>
        <span>Draft</span>
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          disabled={isArchived}
          rows={9}
          maxLength={12000}
        />
      </label>

      <label className={styles.field}>
        <span>Review notes</span>
        <textarea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          disabled={isArchived}
          rows={3}
          maxLength={2000}
        />
      </label>

      {draft.status === "rejected" && draft.review_notes && (
        <p className={styles.reviewNote}>Rejected note: {draft.review_notes}</p>
      )}

      {draft.reviewed_at && (
        <p className={styles.reviewMeta}>Reviewed {formatDate(draft.reviewed_at)}</p>
      )}

      {error && <p className={styles.error}>{error}</p>}

      <footer className={styles.actions}>
        <button
          type="button"
          className={styles.secondaryButton}
          disabled={Boolean(busy) || isArchived}
          onClick={() => void runAction("save", () => onSave(draft.id, payload))}
        >
          {busy === "save" ? "Saving..." : "Save edits"}
        </button>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={Boolean(busy) || isArchived}
          onClick={() => void runAction("approve", () => onApprove(draft.id, payload))}
        >
          {busy === "approve" ? "Approving..." : "Approve"}
        </button>
        <button
          type="button"
          className={styles.dangerButton}
          disabled={Boolean(busy) || isArchived}
          onClick={() => void runAction("reject", () => onReject(draft.id, payload))}
        >
          {busy === "reject" ? "Rejecting..." : "Reject"}
        </button>
        {isApproved && (
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={Boolean(busy)}
            onClick={() => void copyContent()}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        )}
        <button
          type="button"
          className={styles.ghostButton}
          disabled={Boolean(busy) || isArchived}
          onClick={() => void runAction("archive", () => onArchive(draft.id))}
        >
          Archive
        </button>
      </footer>
    </article>
  );
}
