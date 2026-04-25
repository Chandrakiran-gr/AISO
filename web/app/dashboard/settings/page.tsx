"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import styles from "./settings.module.css";
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

const NAV = [
  { icon: "📊", label: "Overview",    href: "/dashboard",              active: false },
  { icon: "🔍", label: "Scan History", href: "/dashboard/scans",       active: false },
  { icon: "🏆", label: "Competitors",  href: "/dashboard/competitors", active: false },
  { icon: "⚡", label: "Action Plan",  href: "/dashboard/actions",     active: false },
  { icon: "⚙️", label: "Settings",     href: "/dashboard/settings",    active: true  },
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
          {saved && <span className={styles.savedPill}>✓ Session active</span>}
          {!saved && hadPrev && (
            <span className={styles.prevPill}>⟳ Re-enter key</span>
          )}
          <a
            href={provider.keyLink}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.getKeyLink}
          >
            Get API key →
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
        <span className={`${styles.guideArrow} ${open ? styles.open : ""}`}>▶</span>
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

// ── Settings Page ──────────────────────────────────────────────────────────────
export default function SettingsPage() {
  return (
    <div className={styles.shell}>
      {/* Sidebar */}
      <aside className={styles.sidebar} aria-label="Dashboard navigation">
        <Link href="/" className={styles.sidebarLogo}>
          <span className={styles.logoMark}>◆</span>
          <span className="gradient-text">AISO</span>
        </Link>
        <div className={styles.sidebarSection}>
          <span className={styles.sidebarLabel}>Workspace</span>
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`${styles.navItem} ${item.active ? styles.active : ""}`}
            >
              <span className={styles.navIcon}>{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </div>
        <div className={styles.sidebarSpacer} />
        <div className={styles.sidebarFooter}>
          <span className={styles.userEmail}>chandrakiran.gr25@gmail.com</span>
          <button className={styles.signOutBtn}>Sign out</button>
        </div>
      </aside>

      {/* Main */}
      <main className={styles.main}>
        <div className={styles.topBar}>
          <span className={styles.pageTitle}>Settings</span>
        </div>

        <div className={styles.content}>
          {/* API Keys section */}
          <section className={styles.section} aria-labelledby="api-keys-heading">
            <h2 id="api-keys-heading" className={styles.sectionTitle}>
              API Keys — Bring Your Own Key (BYOK)
            </h2>

            {/* Trust banner */}
            <div className={styles.trustBanner} role="note">
              <span className={styles.trustIcon}>🔒</span>
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

            {/* Per-provider rows */}
            <div className={styles.providerRows}>
              {PROVIDERS.map((p) => (
                <ProviderKeyRow key={p.id} provider={p} />
              ))}
            </div>

            {/* How-to guide */}
            <KeyGuide />
          </section>
        </div>
      </main>
    </div>
  );
}
