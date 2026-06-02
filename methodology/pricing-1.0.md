# AISO Freemium and BYOK Pricing Model — Specification v1.0.0

**Status:** Active
**Effective from:** 2026-06-01

## Core decision

- **No managed-key free tier.** Variable cost ($10–$27/scan) makes it economically suicidal.
- **BYOK Free tier** as no-cost on-ramp (cost to AISO: ~$0.50–$2/scan = DB + compute only).
- **14-day reverse-style trial on managed keys** with single-scan cap, credit-card-required (opt-out).
- BYOK positioned as **trust/control tier at parity with managed**, not as discount tier.

## Pricing tiers

| Tier | Price/mo | Included | Mode | Cap | Notes |
|---|---|---|---|---|---|
| **Free (BYOK)** | $0 | 0 managed scans | BYOK only | 4 scans/mo, 1 brand, 20 prompts, 2 providers (OpenAI + Anthropic), N=3, 30-day retention | Domain verification + workspace email required |
| **Starter** | $149 | 8 managed scans | Managed or BYOK | 1 brand, 30 prompts, all 4 providers, N=5, 90-day retention | Email support 48hr |
| **Growth** ⭐ | $449 | 24 managed scans + $18/scan overage | Managed or BYOK | 3 brands, 50 prompts, all 4 providers, N=5, 12-mo retention, CAI export | Priority email 24hr |
| **Scale** | $1,290 | 120 managed scans + $15/scan overage | Managed or BYOK | 10 brands, 100 prompts, N=5 or N=8 option, audit log, API access | Founder Slack, 4hr SLA |
| **Enterprise** | from $5,000 | Custom | Both | SSO, methodology pinning, DPA, dedicated capacity | Talk to founder |

## Trial mechanics

- 14 days, credit card required (opt-out trial).
- 1 free managed-key scan during trial.
- Day-1, day-7, day-12 emails.
- Day 14: charge OR one-click downgrade to BYOK Free.

**Why opt-out CC-required:** First Page Sage 2025 — 48.8% organic conversion (opt-out) vs 18.2% (opt-in). Patrick McKenzie at Stripe: requiring CC upfront increases new paying customers on net.

## BYOK architecture

### Key storage

- AWS Secrets Manager (KMS envelope encryption) or Railway secret + master key envelope.
- Per-user reference table: `clients.byok_keys` JSONB column with `{provider: {secret_arn, last4}, ...}`.
- Never logged in plaintext; never returned to client after save.
- Validate via cheap dry-run call before save.

### Per-scan flow

```
At scan time:
  1. Assume short-lived IAM role
  2. Read secret from Secrets Manager
  3. Decrypt in-memory
  4. Make provider API call
  5. Never write plaintext to logs/DB/error reports
```

### Daily health check

- 1 cheap API call per provider per active BYOK customer
- Email alert on revocation
- Scan pause if key invalid

## Cost economics

### Fixed monthly cost (solo founder pre-revenue)

| Item | Estimate |
|---|---|
| Railway + Postgres + S3 | $200–$400 |
| Cloudflare (Turnstile, R2, Workers) | $20–$50 |
| Domain + email + Stripe + tools | $80–$150 |
| Sonnet 4 (classifier baseline) | $50–$150 |
| **Total fixed** | **$350–$750/mo** |

### Variable cost per scan

- Provider tokens (4 providers × 50 prompts × N=5 × ~1.5M output tokens): **$8–$25**
- Classifier (Sonnet 4 hybrid): **~$1.50**
- DB + compute + storage: **~$0.50**
- **Managed-key total: $10–$27**
- **BYOK total (to AISO): ~$2** (user pays the $8–$25)

### Target blended COGS ≤ $12/scan via:

1. Prompt-level caching across customers (shared Core questions)
2. OpenAI Batch API (50% discount on non-urgent requests)
3. N-stepping (N=3 for Tail prompts in adaptive design)
4. Provider rate-card negotiation at scale

### Growth tier margin sanity check

- 24 included scans × $12 = $288 → **36% gross margin at cap**
- Overage at $18 → ~50% margin per overage scan

## Anti-abuse

| Layer | Mechanism | Friction |
|---|---|---|
| Signup | Cloudflare Turnstile (free, invisible) | None |
| Signup | Workspace email required (block gmail/outlook/disposable) | Low |
| Signup | Domain verification (DNS TXT or Google Search Console) | Medium — but product is brand-scoped |
| Signup | One trial per verified domain | Low |
| Trial | Stripe Radar (free with Stripe) | None |
| Free tier | BYOK requirement (provider phone-verifies, etc.) | High — by design |

## Path to $100K ARR

ARPU blend (50% Starter / 35% Growth / 12% Scale / 3% Enterprise): ~$456/mo ≈ $5,476/yr.

| Mix | Customers needed |
|---|---|
| Pure Starter | 56 |
| Pure Growth | 19 |
| **Mixed blend** | **~18 paying customers** |

LTV @ 70% margin, 5% churn: $456 × 0.70 / 0.05 = **$6,384**.
Target CAC < $2,128 (3:1 LTV/CAC). Realistic founder-led: $300–$1,000.

## Stripe products setup

```
Product: aiso_starter           Recurring $149/mo  14-day trial  payment_behavior=default_incomplete
Product: aiso_growth            Recurring $449/mo  14-day trial
Product: aiso_scale             Recurring $1,290/mo 14-day trial
Product: aiso_overage_starter   Metered $20/unit
Product: aiso_overage_growth    Metered $18/unit
Product: aiso_overage_scale     Metered $15/unit
Product: aiso_enterprise        Quote-only, Stripe Invoicing

Webhooks:
  invoice.payment_failed             → 7-day grace, then downgrade to Free
  customer.subscription.trial_will_end (72h before)  → Day 12 email
  customer.subscription.updated      → sync entitlements
  customer.subscription.deleted      → tier = free
```

## Onboarding flows

### Trial path

1. Visitor → /pricing → "Start 14-day Trial"
2. Workspace email + Turnstile → magic link
3. Brand domain entry → DNS TXT verification (or GSC OAuth)
4. Credit card (Stripe Elements; no charge until trial end)
5. Welcome → "Run first scan?" → 1 free managed-key scan
6. Day-1, day-7, day-12 emails
7. Day-14: charge OR downgrade to Free BYOK

### BYOK Free path

1. Visitor → /pricing → "Get Started Free"
2. Email + Turnstile → magic link
3. Brand domain + DNS verify
4. BYOK wizard: OpenAI + Anthropic key entry with annotated screenshots
5. Validate keys (1 cheap API call per provider)
6. Save to AWS Secrets Manager
7. Schedule first scan

## Version bump rules

| Change | Bump |
|---|---|
| Tier prices change | Minor (pricing-1.1); grandfather existing customers |
| New tier added | Minor |
| Tier removed | Major (pricing-2.0); grandfather forever |
| Trial length / mechanics change | Patch |
| Overage rates change | Patch; grandfather |

## Limitations

1. No public AVS-platform conversion data exists; benchmarks (3-5% freemium, 31-49% opt-out trial) from general SaaS.
2. 4-provider scan COGS is volatile; budget 30% COGS reduction over 12 months but don't price on it.
3. BYOK key revocation operational risk (~10% of BYOK users need support monthly).
4. Solo founder bandwidth is real constraint; ≤4 tiers maximum sustainable.
5. Pricing experimentation has a floor; <50 paying customers = qualitative only.

## References

- Kumar, "Making Freemium Work" (HBR May 2014) — 2–5% conversion benchmark
- Ramanujam, *Monetizing Innovation* (2016) — Good/Better/Best pricing
- Nagle, Hogan & Zale, *The Strategy and Tactics of Pricing* — fencing taxonomy
- First Page Sage 2025 — 48.8% organic CC opt-out trial conversion
- Poyar/OpenView/Pendo 2023 — freemium vs trial vs reverse trial data
- JetBrains AI BYOK (Dec 2025) — BYOK-at-parity precedent
- PlanetScale March 2024 — cautionary tale on killing free tier
