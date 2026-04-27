"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import styles from "./onboarding.module.css";
import { setKey, getKey, getAllKeys, hadKeyPreviousSession, type Provider } from "@/lib/byok";
import { INTENT_GROUPS } from "@/lib/intent-groups";

const PROVIDERS = [
  { id: "openai",     name: "ChatGPT",    color: "#10a37f" },
  { id: "claude",     name: "Claude",     color: "#e8b68a" },
  { id: "perplexity", name: "Perplexity", color: "#1fb8cd" },
  { id: "gemini",     name: "Gemini",     color: "#4285f4" },
];

const GROUPS = INTENT_GROUPS;

const STEPS = [
  { num: 1, label: "Discover" },
  { num: 2, label: "Configure" },
  { num: 3, label: "Launch" },
];

const SCAN_STEPS = [
  "Generating query bank…",
  "Querying ChatGPT…",
  "Querying Claude…",
  "Querying Perplexity…",
  "Querying Gemini…",
  "Analysing brand mentions…",
  "Computing visibility score…",
];

function getInitialKeySet(): Partial<Record<Provider, boolean>> {
  const state: Partial<Record<Provider, boolean>> = {};
  for (const p of PROVIDERS) {
    state[p.id as Provider] = Boolean(getKey(p.id as Provider));
  }
  return state;
}

interface FormState {
  businessName: string;
  websiteUrl:   string;
  industry:     string;
  location:     string;
  competitors:  string;
  providers:    string[];
  groups:       string[];
}

const DEFAULT: FormState = {
  businessName: "",
  websiteUrl:   "",
  industry:     "",
  location:     "",
  competitors:  "",
  providers:    ["openai", "claude", "perplexity", "gemini"],
  groups:       ["G1", "G2", "G3"],
};

// ── Step 1: Discover ──────────────────────────────────────────────────────────
function Step1({ form, set, onNext }: { form: FormState; set: (f: FormState) => void; onNext: () => void }) {
  const valid = form.businessName.trim().length > 0 && form.websiteUrl.startsWith("http");
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (valid) onNext(); }}>
      <span className={styles.stepBadge}>Step 1 of 3 · Discover</span>
      <h2 className={styles.stepTitle}>Tell us about your business</h2>
      <p className={styles.stepSubtitle}>
        We&apos;ll use this to generate targeted questions across AI platforms and benchmark against your competitors.
      </p>
      <div className={styles.fields}>
        <div className={styles.fieldGroup}>
          <label className={styles.label} htmlFor="ob-name">Business name *</label>
          <input id="ob-name" className="input" type="text" placeholder="Your business name"
            value={form.businessName} onChange={(e) => set({ ...form, businessName: e.target.value })} maxLength={200} required />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.label} htmlFor="ob-url">Website URL *</label>
          <input id="ob-url" className="input" type="url" placeholder="https://yourbusiness.com"
            value={form.websiteUrl} onChange={(e) => set({ ...form, websiteUrl: e.target.value })} maxLength={500} required />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-sm)" }}>
          <div className={styles.fieldGroup}>
            <label className={styles.label} htmlFor="ob-industry">Industry</label>
            <input id="ob-industry" className="input" type="text" placeholder="e.g. Coffee shop, SaaS"
              value={form.industry} onChange={(e) => set({ ...form, industry: e.target.value })} maxLength={110} />
          </div>
          <div className={styles.fieldGroup}>
            <label className={styles.label} htmlFor="ob-location">Location</label>
            <input id="ob-location" className="input" type="text" placeholder="e.g. City, State"
              value={form.location} onChange={(e) => set({ ...form, location: e.target.value })} maxLength={100} />
          </div>
        </div>
        <div className={styles.fieldGroup}>
          <div className={styles.labelRow}>
            <label className={styles.label} htmlFor="ob-competitors">Main competitors</label>
            <span className={styles.labelHint}>Optional — improves benchmarking</span>
          </div>
          <input id="ob-competitors" className="input" type="text" placeholder="Competitor A, Competitor B"
            value={form.competitors} onChange={(e) => set({ ...form, competitors: e.target.value })} maxLength={500} />
        </div>
      </div>
      <div className={styles.navRow}>
        <div />
        <button type="submit" className={styles.nextBtn} disabled={!valid} id="ob-step1-next">
          Next: Configure →
        </button>
      </div>
    </form>
  );
}

// ── Step 2: Configure ─────────────────────────────────────────────────────────
function Step2({ form, set, onBack, onNext }: {
  form: FormState; set: (f: FormState) => void; onBack: () => void; onNext: () => void;
}) {
  const [keysOpen, setKeysOpen] = useState(false);
  // Track which providers have keys in this session
  const [keySet, setKeySet] = useState<Partial<Record<Provider, boolean>>>(
    getInitialKeySet
  );

  function handleKeyInput(provider: Provider, value: string) {
    if (value.trim()) {
      setKey(provider, value.trim());
      setKeySet((prev) => ({ ...prev, [provider]: true }));
    }
  }

  const toggleProvider = (id: string) => {
    const next = form.providers.includes(id) ? form.providers.filter((p) => p !== id) : [...form.providers, id];
    if (next.length > 0) set({ ...form, providers: next });
  };
  const toggleGroup = (id: string) => {
    const next = form.groups.includes(id) ? form.groups.filter((g) => g !== id) : [...form.groups, id];
    if (next.length > 0) set({ ...form, groups: next });
  };

  const anyKeySet = PROVIDERS.some((p) => keySet[p.id as Provider]);

  return (
    <div>
      <span className={styles.stepBadge}>Step 2 of 3 · Configure</span>
      <h2 className={styles.stepTitle}>Configure your scan</h2>
      <p className={styles.stepSubtitle}>
        Choose which AI platforms to monitor and which question groups to include. You can change these any time.
      </p>
      <div className={styles.fields}>
        <div className={styles.fieldGroup}>
          <label className={styles.label}>AI platforms to monitor</label>
          <div className={styles.providerGrid}>
            {PROVIDERS.map((p) => (
              <label key={p.id} className={styles.providerOption}>
                <input type="checkbox" checked={form.providers.includes(p.id)} onChange={() => toggleProvider(p.id)} />
                <span className={styles.providerDot} style={{ background: p.color }} />
                <span className={styles.providerName}>{p.name}</span>
                <span className={styles.checkIndicator}>✓</span>
              </label>
            ))}
          </div>
        </div>
        <div className={styles.fieldGroup}>
          <div className={styles.labelRow}>
            <label className={styles.label}>Question intent groups</label>
            <span className={styles.labelHint}>{form.groups.length}/7 selected</span>
          </div>
          <div className={styles.groupTags}>
            {GROUPS.map((g) => (
              <button key={g.id} type="button" title={g.desc}
                className={`${styles.groupTag} ${form.groups.includes(g.id) ? styles.selected : ""}`}
                onClick={() => toggleGroup(g.id)}>
                {g.id} · {g.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── BYOK: collapsed by default ────────────────────────── */}
        <div className={styles.fieldGroup}>
          <button
            type="button"
            className={styles.byokToggle}
            onClick={() => setKeysOpen((o) => !o)}
            aria-expanded={keysOpen}
            id="ob-byok-toggle"
          >
            <span className={`${styles.byokArrow} ${keysOpen ? styles.byokArrowOpen : ""}`}>▶</span>
            {anyKeySet
              ? `🔑 API keys added (${PROVIDERS.filter((p) => keySet[p.id as Provider]).length} of 4)`
              : "+ Add your own API keys to run all platforms"}
          </button>

          {keysOpen && (
            <div className={styles.byokPanel}>
              <p className={styles.byokTrust}>
                🔒 <strong>Never saved to our servers.</strong> Keys are stored only in your browser&apos;s session memory and cleared when you close this tab.
                {" "}You can manage them anytime in{" "}
                <a href="/dashboard/settings" target="_blank" style={{ color: "var(--accent-teal)" }}>Settings</a>.
              </p>
              <div className={styles.byokFields}>
                {PROVIDERS.map((p) => (
                  <div key={p.id} className={styles.byokRow}>
                    <span className={styles.byokProvider}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: p.color, display: "inline-block", marginRight: 6 }} />
                      {p.name}
                    </span>
                    {keySet[p.id as Provider]
                      ? <span className={styles.byokSaved}>✓ Session active</span>
                      : hadKeyPreviousSession(p.id as Provider)
                      ? <span className={styles.byokPrev}>⟳ Re-enter key</span>
                      : null
                    }
                    <input
                      type="password"
                      className={`input ${styles.byokInput}`}
                      placeholder={keySet[p.id as Provider] ? "••••••••" : `Paste your ${p.name} API key`}
                      autoComplete="off"
                      spellCheck={false}
                      onBlur={(e) => handleKeyInput(p.id as Provider, e.target.value)}
                      onChange={(e) => { if (!e.target.value) setKeySet((prev) => ({ ...prev, [p.id]: false })); }}
                    />
                    <a
                      href={p.id === "openai" ? "https://platform.openai.com/api-keys"
                        : p.id === "claude" ? "https://console.anthropic.com/settings/keys"
                        : p.id === "perplexity" ? "https://www.perplexity.ai/settings/api"
                        : "https://aistudio.google.com/app/apikey"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={styles.byokGetKey}
                    >
                      Get key →
                    </a>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        {/* ── end BYOK ──────────────────────────────────────────── */}

      </div>
      <div className={styles.navRow}>
        <button type="button" className={styles.backBtn} onClick={onBack}>← Back</button>
        <button type="button" className={styles.nextBtn} onClick={onNext} id="ob-step2-next">
          Review &amp; Launch →
        </button>
      </div>
    </div>
  );
}

// ── Step 3: Launch ────────────────────────────────────────────────────────────
function Step3({ form, onBack, onLaunch, scanning, scanIdx, error, skipped }: {
  form: FormState; onBack: () => void; onLaunch: () => void;
  scanning: boolean; scanIdx: number;
  error: string | null; skipped: string[];
}) {
  const providerNames = form.providers.map((id) => PROVIDERS.find((p) => p.id === id)?.name).join(", ");

  if (scanning) {
    return (
      <div className={styles.scanRunning}>
        <div className={styles.scanSpinner} />
        <div>
          <p style={{ fontWeight: 600, fontSize: "1rem", marginBottom: 4 }}>Running your scan…</p>
          <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
            This takes around 8 minutes. You&apos;ll see your AI Visibility Score when done.
          </p>
        </div>
        <div className={styles.scanProgress}>
          <div className={styles.scanProgressTrack}>
            <div className={styles.scanProgressFill} />
          </div>
        </div>
        <p className={styles.scanStep}>{SCAN_STEPS[scanIdx]}</p>
      </div>
    );
  }

  return (
    <div>
      {error && (
        <div style={{
          background: "rgba(239,68,68,0.08)",
          border: "1px solid rgba(239,68,68,0.25)",
          borderRadius: "var(--radius-md)",
          padding: "10px 14px",
          fontSize: "0.8125rem",
          color: "#f87171",
          marginBottom: "var(--space-md)",
        }}>
          ⚠ {error}
        </div>
      )}
      {skipped.length > 0 && (
        <div style={{
          background: "rgba(251,191,36,0.06)",
          border: "1px solid rgba(251,191,36,0.2)",
          borderRadius: "var(--radius-md)",
          padding: "10px 14px",
          fontSize: "0.8125rem",
          color: "#fbbf24",
          marginBottom: "var(--space-md)",
        }}>
          ⚡ Skipped (no API key): {skipped.join(", ")}. Add keys in{" "}
          <a href="/dashboard/settings" style={{ color: "var(--accent-teal)" }}>Settings</a>.
        </div>
      )}
      <div className={styles.launchContent}>
        <div className={styles.launchIcon}>🚀</div>
        <div>
          <h2 className={styles.stepTitle}>Ready to launch</h2>
          <p className={styles.stepSubtitle} style={{ marginBottom: 0 }}>
            Review your scan configuration, then hit Launch to start your first AI visibility scan.
          </p>
        </div>
        <div className={styles.scanSummary}>
          {[
            { k: "Business",  v: form.businessName },
            { k: "Website",   v: form.websiteUrl },
            { k: "Industry",  v: form.industry  || "—" },
            { k: "Location",  v: form.location  || "—" },
            { k: "Platforms", v: providerNames },
            { k: "Groups",    v: form.groups.join(", ") },
          ].map(({ k, v }) => (
            <div key={k} className={styles.summaryRow}>
              <span className={styles.summaryKey}>{k}</span>
              <span className={styles.summaryVal}>{v}</span>
            </div>
          ))}
        </div>
      </div>
      <div className={styles.navRow}>
        <button type="button" className={styles.backBtn} onClick={onBack}>← Back</button>
        <button type="button" className={styles.nextBtn} onClick={onLaunch} id="ob-launch-btn">
          🚀 Launch scan
        </button>
      </div>
    </div>
  );
}

// ── API helpers ───────────────────────────────────────────────────────────────
const API = "/api/proxy";

async function createClient(slug: string, displayName: string): Promise<string> {
  const res = await fetch(`${API}/v1/clients`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: slug, display_name: displayName }),
  });
  if (res.status === 409) {
    // Client already exists — reuse the slug as ID
    return res.headers.get("X-Client-Id") ?? slug;
  }
  if (!res.ok) throw new Error(`Failed to create client (${res.status})`);
  const data = await res.json();
  return data.id as string;
}

async function createScan(
  clientId: string,
  providers: string[],
  groups: string[],
  byokKeys: Record<string, string>,
): Promise<string> {
  const res = await fetch(`${API}/v1/clients/${clientId}/scans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: clientId,
      providers,
      groups,
      byok_keys: Object.keys(byokKeys).length > 0 ? byokKeys : undefined,
    }),
  });
  if (!res.ok) throw new Error(`Failed to create scan (${res.status})`);
  const data = await res.json();
  return data.id as string;
}

async function pollScan(clientId: string, scanId: string): Promise<{
  status: string;
  skipped_providers?: string[];
}> {
  const res = await fetch(`${API}/v1/clients/${clientId}/scans/${scanId}`);
  if (!res.ok) throw new Error(`Scan poll failed (${res.status})`);
  return res.json();
}

function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 50);
}

// ── Main Wizard ───────────────────────────────────────────────────────────────
export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep]           = useState(1);
  const [form, setForm]           = useState<FormState>(DEFAULT);
  const [scanning, setScanning]   = useState(false);
  const [scanIdx, setScanIdx]     = useState(0);
  const [error, setError]         = useState<string | null>(null);
  const [skipped, setSkipped]     = useState<string[]>([]);
  const pollRef                   = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!scanning) return;
    const id = setInterval(() => setScanIdx((i) => (i + 1) % SCAN_STEPS.length), 1800);
    return () => clearInterval(id);
  }, [scanning]);

  // Clean up poller on unmount
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  async function handleLaunch() {
    setError(null);
    setScanning(true);

    try {
      // 1. Create / reuse client record
      const clientId = await createClient(
        slugify(form.businessName),
        form.businessName,
      );

      // 2. Collect BYOK keys from sessionStorage (never logged)
      const byokKeys = getAllKeys(); // { openai?: string, claude?: string, ... }

      // 3. Fire the scan
      const scanId = await createScan(clientId, form.providers, form.groups, byokKeys);

      // 4. Poll until complete / failed
      pollRef.current = setInterval(async () => {
        try {
          const result = await pollScan(clientId, scanId);
          if (result.status === "complete" || result.status === "failed") {
            clearInterval(pollRef.current!);
            if (result.skipped_providers?.length) {
              setSkipped(result.skipped_providers);
            }
            // Short pause so the user sees the final scan step
            setTimeout(() => router.push("/dashboard"), 1500);
          }
        } catch {
          // Poll errors are transient — keep retrying
        }
      }, 4000);
    } catch (err) {
      setScanning(false);
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    }
  }

  const progress = ((step - 1) / (STEPS.length - 1)) * 100;

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <div className={styles.topLogo}>
          <span className={styles.logoMark}>◆</span>
          <span className="gradient-text">AISO</span>
        </div>
        <span className={styles.stepCounter}>Step {step} of {STEPS.length}</span>
      </div>

      <div className={styles.progressTrack}>
        <div className={styles.progressFill} style={{ width: `${progress}%` }} />
      </div>

      <div className={styles.stepPills}>
        {STEPS.map((s, i) => (
          <div key={s.num} style={{ display: "flex", alignItems: "center" }}>
            <div className={`${styles.stepPill} ${step === s.num ? styles.active : step > s.num ? styles.done : ""}`}>
              <span className={styles.stepNum}>{step > s.num ? "✓" : s.num}</span>
              {s.label}
            </div>
            {i < STEPS.length - 1 && <div className={styles.stepConnector} />}
          </div>
        ))}
      </div>

      <div className={styles.card}>
        {step === 1 && <Step1 form={form} set={setForm} onNext={() => setStep(2)} />}
        {step === 2 && <Step2 form={form} set={setForm} onBack={() => setStep(1)} onNext={() => setStep(3)} />}
        {step === 3 && <Step3 form={form} onBack={() => setStep(2)} onLaunch={handleLaunch} scanning={scanning} scanIdx={scanIdx} error={error} skipped={skipped} />}
      </div>
    </div>
  );
}
