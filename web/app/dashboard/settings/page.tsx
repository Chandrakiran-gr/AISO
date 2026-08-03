"use client";

import { useEffect, useState } from "react";
import styles from "./settings.module.css";
import { signOut } from "next-auth/react";
import {
  setKey, getKey, clearKey, hadKeyPreviousSession,
  type Provider,
} from "@/lib/byok";

// ── Provider config ────────────────────────────────────────────────────────────
const PROVIDERS: { id: Provider; name: string; color: string; keyLink: string; keyHint: string; guide: string }[] = [
  {
    id: "openai",
    name: "ChatGPT (OpenAI)",
    color: "#10a37f",
    keyLink: "https://platform.openai.com/api-keys",
    keyHint: "sk-...",
    guide: `1. Go to <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener">platform.openai.com/api-keys</a><br/>
2. Click <strong>+ Create new secret key</strong><br/>
3. Give it a name (e.g. "AISO") → click Create<br/>
4. Copy the key immediately — it won't be shown again`,
  },
  {
    id: "claude",
    name: "Claude (Anthropic)",
    color: "#e8b68a",
    keyLink: "https://console.anthropic.com/settings/keys",
    keyHint: "sk-ant-...",
    guide: `1. Go to <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com/settings/keys</a><br/>
2. Click <strong>Create Key</strong><br/>
3. Name it (e.g. "AISO") → copy the key`,
  },
  {
    id: "perplexity",
    name: "Perplexity",
    color: "#1fb8cd",
    keyLink: "https://www.perplexity.ai/settings/api",
    keyHint: "pplx-...",
    guide: `1. Go to <a href="https://www.perplexity.ai/settings/api" target="_blank" rel="noopener">perplexity.ai/settings/api</a><br/>
2. Click <strong>+ Generate</strong><br/>
3. Copy the API key shown`,
  },
  {
    id: "gemini",
    name: "Gemini (Google)",
    color: "#4285f4",
    keyLink: "https://aistudio.google.com/app/apikey",
    keyHint: "AIza...",
    guide: `1. Go to <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener">aistudio.google.com/app/apikey</a><br/>
2. Click <strong>Create API key</strong><br/>
3. Select a Google Cloud project (or create one)<br/>
4. Copy the generated key`,
  },
];

// ── Single provider row ────────────────────────────────────────────────────────
function ProviderKeyRow({ provider }: { provider: typeof PROVIDERS[number] }) {
  const [value, setValue]       = useState("");
  const [revealed, setRevealed] = useState(false);
  const [saved, setSaved]       = useState(false);
  const [hadPrev, setHadPrev]   = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const current = getKey(provider.id);
      if (current) {
        setValue(current);
        setSaved(true);
      } else {
        setHadPrev(hadKeyPreviousSession(provider.id));
      }
    }, 0);

    return () => window.clearTimeout(timer);
  }, [provider.id]);

  function handleChange(v: string) {
    setValue(v);
    setSaved(false);
  }

  function handleSave() {
    if (!value.trim()) return;
    setKey(provider.id, value.trim());
    setSaved(true);
    setHadPrev(false);
  }

  function handleClear() {
    clearKey(provider.id);
    setValue("");
    setSaved(false);
    setHadPrev(false);
  }

  return (
    <div
      className={`${styles.providerRow} ${saved ? styles.hasKey : hadPrev ? styles.hadPrev : ""}`}
    >
      <div className={styles.providerRowTop}>
        <div className={styles.providerName}>
          <span className={styles.providerDot} style={{ background: provider.color }} />
          {provider.name}
        </div>
        <div className={styles.providerBadge}>
          {saved && <span className={styles.savedPill}>Session active</span>}
          {!saved && hadPrev && (
            <span className={styles.prevPill}>Re-enter key</span>
          )}
          <a
            href={provider.keyLink}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.getKeyLink}
          >
            Get API key
          </a>
        </div>
      </div>

      <div className={styles.keyInputRow}>
        <input
          id={`byok-${provider.id}`}
          type={revealed ? "text" : "password"}
          className={`input ${styles.keyInput}`}
          placeholder={saved ? "••••••••••••••••" : provider.keyHint}
          value={value}
          onChange={(e) => handleChange(e.target.value)}
          onBlur={() => { if (value.trim()) handleSave(); }}
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="button"
          className={styles.revealBtn}
          onClick={() => setRevealed((r) => !r)}
          aria-label={revealed ? "Hide key" : "Show key"}
        >
          {revealed ? "Hide" : "Show"}
        </button>
        {saved && (
          <button type="button" className={styles.clearBtn} onClick={handleClear}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

// ── How to get keys guide ──────────────────────────────────────────────────────
function KeyGuide() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        className={styles.guideToggle}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className={`${styles.guideArrow} ${open ? styles.open : ""}`}>{">"}</span>
        How to get API keys for each provider
      </button>
      {open && (
        <div className={styles.guideContent} style={{ marginTop: "var(--space-sm)" }}>
          {PROVIDERS.map((p) => (
            <div key={p.id} className={styles.guideProvider}>
              <div className={styles.guideName}>
                <span className={styles.guideDot} style={{ background: p.color }} />
                {p.name}
              </div>
              <div
                className={styles.guideSteps}
                dangerouslySetInnerHTML={{ __html: p.guide }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Danger zone: delete account ─────────────────────────────────────────────────
const DELETE_PHRASE = "I confirm to delete my account";

function DeleteAccountSection() {
  const [open, setOpen]         = useState(false);
  const [phrase, setPhrase]     = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError]       = useState<string | null>(null);

  const canDelete = phrase.trim() === DELETE_PHRASE && !deleting;

  async function handleDelete() {
    if (!canDelete) return;
    setDeleting(true);
    setError(null);
    try {
      const res = await fetch("/api/proxy/v1/auth/remove-account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: phrase.trim() }),
      });
      if (!res.ok) {
        setError("We couldn't delete your account. Please try again.");
        setDeleting(false);
        return;
      }
      // Account + all data gone — end the session and return home.
      await signOut({ callbackUrl: "/" });
    } catch {
      setError("Network error. Please try again.");
      setDeleting(false);
    }
  }

  return (
    <section className={styles.section} aria-labelledby="danger-heading">
      <h2 id="danger-heading" className={styles.sectionTitle}>Danger Zone</h2>

      <div
        style={{
          border: "1px solid rgba(229,72,77,0.4)",
          borderRadius: 12,
          padding: "16px 18px",
          background: "rgba(229,72,77,0.06)",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <strong style={{ color: "#e5484d" }}>Delete account</strong>
        <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--text-muted, #9aa)", lineHeight: 1.5 }}>
          Permanently delete your account and all associated data — businesses, scans,
          reports, conversations, and history. This cannot be undone.
        </p>
        <div>
          <button
            type="button"
            onClick={() => { setPhrase(""); setError(null); setOpen(true); }}
            style={{
              marginTop: 6,
              padding: "9px 16px",
              borderRadius: 8,
              cursor: "pointer",
              border: "1px solid #e5484d",
              background: "transparent",
              color: "#e5484d",
              fontWeight: 600,
              fontSize: "0.9rem",
            }}
          >
            Delete my account
          </button>
        </div>
      </div>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-modal-title"
          onClick={(e) => { if (e.target === e.currentTarget && !deleting) setOpen(false); }}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1000,
            background: "rgba(0,0,0,0.6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <div
            style={{
              width: "100%",
              maxWidth: 460,
              background: "var(--bg-card, #16181d)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 14,
              padding: 24,
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            <h3 id="delete-modal-title" style={{ margin: 0, fontSize: "1.1rem" }}>
              Delete your account?
            </h3>
            <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--text-muted, #9aa)", lineHeight: 1.5 }}>
              This permanently deletes your profile and <strong>all related data</strong>.
              This action cannot be undone.
            </p>
            <label htmlFor="delete-confirm" style={{ fontSize: "0.85rem" }}>
              Type <strong style={{ color: "#e5484d" }}>{DELETE_PHRASE}</strong> to confirm
            </label>
            <input
              id="delete-confirm"
              className="input"
              type="text"
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              placeholder={DELETE_PHRASE}
              autoComplete="off"
              spellCheck={false}
              autoFocus
            />
            {error && (
              <div role="alert" style={{ color: "#e5484d", fontSize: "0.85rem" }}>{error}</div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 4 }}>
              <button
                type="button"
                onClick={() => setOpen(false)}
                disabled={deleting}
                style={{
                  padding: "9px 16px",
                  borderRadius: 8,
                  cursor: "pointer",
                  border: "1px solid rgba(255,255,255,0.2)",
                  background: "transparent",
                  color: "var(--text, #eee)",
                  fontSize: "0.9rem",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={!canDelete}
                style={{
                  padding: "9px 16px",
                  borderRadius: 8,
                  cursor: canDelete ? "pointer" : "not-allowed",
                  border: "none",
                  background: canDelete ? "#e5484d" : "rgba(229,72,77,0.4)",
                  color: "#fff",
                  fontWeight: 600,
                  fontSize: "0.9rem",
                }}
              >
                {deleting ? "Deleting…" : "Delete account"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

// ── Settings Page ──────────────────────────────────────────────────────────────
export default function SettingsPage() {
  return (
    <div className={styles.main}>
      <div className={styles.topBar}>
        <span className={styles.pageTitle}>Settings</span>
      </div>

      <div className={styles.content}>
        <section className={styles.section} aria-labelledby="api-keys-heading">
          <h2 id="api-keys-heading" className={styles.sectionTitle}>
            API Keys — Bring Your Own Key (BYOK)
          </h2>

          <div className={styles.trustBanner} role="note">
            <span className={styles.trustIcon}>BYOK</span>
            <div className={styles.trustText}>
              <strong className={styles.trustTitle}>Your keys are never saved to our servers</strong>
              <p className={styles.trustDesc}>
                API keys are stored only in your browser&apos;s session memory (sessionStorage).
                They are sent directly to our scan engine over HTTPS and discarded immediately after use.
                Closing this browser tab clears them permanently — we have no record of them.
                You can{" "}
                <a
                  href="https://developer.chrome.com/docs/devtools/storage/sessionstorage/"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "var(--accent-teal)" }}
                >
                  inspect this in DevTools
                </a>{" "}
                to verify.
              </p>
            </div>
          </div>

          <div className={styles.providerRows}>
            {PROVIDERS.map((p) => (
              <ProviderKeyRow key={p.id} provider={p} />
            ))}
          </div>

          <KeyGuide />
        </section>

        <DeleteAccountSection />
      </div>
    </div>
  );
}
