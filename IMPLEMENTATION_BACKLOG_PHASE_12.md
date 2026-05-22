# AISO Implementation Backlog — Phase 12 Addendum

**Append to `IMPLEMENTATION_BACKLOG.md` after Phase 11.**

Phase 12 implements the upstream pipeline (`pipeline-1.0.md`): onboarding, question generation, scoring, and selection. This replaces the prior question-generation logic in `api/question_generation.py`.

---

## Phase 12 — Upstream Pipeline (8–10 days)

### 12.1 Business profile schema and intake API (1 day)

- Apply DDL from `/methodology/pipeline-1.0.md` Postgres schema additions.
- New endpoint: `POST /v1/onboarding/start` — creates client + business_profile shell, returns onboarding_id.
- New endpoint: `PATCH /v1/onboarding/{id}` — updates profile fields incrementally.
- New endpoint: `POST /v1/onboarding/{id}/submit` — validates Minimum Context Floor, returns either OK or 400 with missing-fields list.
- **Acceptance:** create a client, patch fields one-at-a-time, submit; verify floor enforcement by submitting incomplete profile → 400 with field names.

### 12.2 Vertical-conditioned intake forms (2 days)

- Implement 3 verticals first: `b2b_saas`, `local_services`, `ecommerce`.
- Each vertical has a config file `intake_schemas/{vertical}.yml` defining required + optional fields with validators.
- Frontend renders form dynamically from schema.
- Hard-coded Minimum Context Floor per `pipeline-1.0.md` §A.2.
- **Acceptance:** sign up as B2B SaaS, complete intake; verify all required fields enforced; verify floor blocks submission when any required field empty.

### 12.3 Crawler (2 days)

- New module: `api/crawler/`.
- Tier 1 endpoints: homepage, /about, /products|/services, /pricing, /customers, /blog, /robots.txt, /sitemap.xml, structured data.
- Use Playwright headless Chromium for JS-rendered SPAs.
- Hard timeout 60s; graceful "we couldn't fully crawl" message.
- Output: structured `crawl_artifacts` JSONB → `business_profile.crawl_artifacts`.
- Extract schema.org LocalBusiness, Product, Service, Organization, Offer, FAQPage entities.
- **Acceptance:** crawl 5 known sites (1 B2B SaaS, 1 local dentist with LocalBusiness schema, 1 ecommerce with Product schema, 1 SPA, 1 site that times out); verify expected fields extracted from each.

### 12.4 LLM profile draft + customer confirmation (1 day)

- After crawl: Claude Sonnet 4 generates draft business profile from crawl_artifacts.
- Frontend shows draft with each field flagged "crawled" / "guessed" / "needs you".
- Customer edits and confirms.
- **Acceptance:** crawl a known site; verify draft populates known-good fields; verify "needs you" flag appears on ICP, competitors, objective.

### 12.5 Question generation engine (1 day)

- New module: `api/question_gen/`.
- Generation prompt from `pipeline-1.0.md` §B.2 (verbatim, hash-chained).
- Few-shot library files: `prompts/question_gen_fewshots/{vertical}.yml` with 10–15 hand-written examples per starting vertical.
- Generate `target_n * 3` candidates (default 150 for cold-start scan).
- Persist all candidates to `question_candidate` table.
- **Acceptance:** generate candidates for a B2B SaaS profile; verify 150 candidates created; verify distribution across Journey×Frame matches §A.5 weights for the stated objective ±10%.

### 12.6 Realism filter (1 day)

- New module: `api/question_gen/realism.py`.
- Claude Sonnet 4 LLM-judge prompt from `pipeline-1.0.md` §B.3.
- n=3 self-consistency.
- Length penalty per §B.3.
- Threshold ≥7/10 to pass.
- Defer Faruqui-Das classifier (`w2 = 0`) at v1.
- Persist `realism_score` to `question_candidate.realism_score`.
- **Acceptance:** feed 20 known-bad questions (keyword stuffing, template residue) and 20 known-good questions; verify ≥18/20 good pass and ≥18/20 bad fail.

### 12.7 Scorer (1 day)

- New module: `api/question_gen/scorer.py`.
- Scorer prompt from `pipeline-1.0.md` §C.2.
- 5 dimensions per question (D1–D5), weighted per §C.1.
- n=3 self-consistency, Gwet AC2 ≥0.75 gate.
- Persist all scores to `question_score` table.
- Hash-chain scorer prompt + weights version.
- **Acceptance:** score 20 candidates; verify all 5 dimensions populated; verify weighted_score = 0.30·D1 + 0.25·D2 + 0.20·D3 + 0.15·D4 + 0.10·D5 to 3 decimal places.

### 12.8 Constrained selection MIP (1 day)

- New module: `api/question_gen/selector.py`.
- Implement MIP from `pipeline-1.0.md` §C.3 using `pulp` library.
- Constraints: target_n, critical_question_ids, journey_min, frame_min, intent_band, personas.
- λ_MMR = 0.7 default; 0.6 for cold-start, 0.75 for steady-state.
- Embedding similarity via `text-embedding-3-small` or open-source equivalent.
- Persist `selected = true` on chosen questions.
- **Acceptance:** select 50 from 150 candidates with all default constraints; verify (a) target_n hit exactly, (b) every J1–J4 has ≥2 questions, (c) every frame has ≥1 question, (d) intent distribution within band, (e) no critical question dropped, (f) solver returns in <2 seconds.

### 12.9 Founder-review checkpoint (1 day)

- After selection, scan stays in `awaiting_founder_review` state.
- Slack notification to founder webhook with summary: customer, vertical, objective, 50 questions grouped by Journey×Frame.
- Founder UI: review questions, edit/remove any, approve.
- On approve: scan transitions to `ready`, `ScanExecutor.enqueue` called.
- **Acceptance:** complete onboarding through selection; verify Slack notification fires; founder approves; verify scan_run transitions to `ready` and Procrastinate job enqueued.

### 12.10 First-scan acceptance gate (0.5 day)

- After scan completes, before showing report: check Presence ≥1 for ≥60% of questions where brand is the explicit subject (brand_frame = 'brand_only' or 'branded_comparison' with customer's brand in text).
- If fails: do NOT show report; route to founder review with reason; suggest portfolio rework.
- **Acceptance:** simulate a scan where 50% brand-explicit questions return Presence=0; verify gate fails and routes to founder.

### 12.11 Founder-review graduation logic (0.5 day)

- Track per-scan: operator flag rate, first-scan gate pass/fail, LLM-judge-vs-spot-check AC2.
- Compute rolling 3-month metrics.
- When all 3 thresholds (`pipeline-1.0.md` §A.7) hold for 3 consecutive months: emit `founder_review_graduated` event; switch to sampled-review mode.
- **Acceptance:** seed test data with passing thresholds for 3 months; verify graduation event fires; seed failing data; verify graduation does not fire.

---

## Phase 12 acceptance — end-to-end test

After all 11 phases pass:

1. Sign up new customer as `b2b_saas` with `preference` objective.
2. Crawl + draft profile (verify auto-extracted fields populated).
3. Customer confirms profile (verify floor enforcement on missing competitors).
4. Generate 150 candidates (verify distribution, persistence).
5. Realism filter (verify failures < 30%).
6. Score remaining candidates (verify all 5 dimensions, AC2 ≥0.75).
7. Select 50 (verify all coverage constraints satisfied).
8. Founder review (verify Slack notification, approve in UI).
9. Scan executes via Procrastinate (verify all 7 prior phases' acceptance criteria continue to pass).
10. First-scan acceptance gate evaluated.
11. Report shown to customer (or routed to founder review on gate failure).
12. Every action above logged to `audit_event` with hash chain intact.

If all 12 steps pass for 3 consecutive test runs, Phase 12 is complete. Tag `aiso-phase-12-complete`.

---

## Out of scope for Phase 12

- Faruqui-Das wellformedness classifier (Stage 4 / post-launch)
- 200-question gold set construction (manual, 2-week founder + 2 contractor effort, parallel)
- 6 remaining verticals (add one per quarter as customers arrive)
- Steady-state branching (presumes ≥3 scans of history per customer)
- Multi-turn question probes
- Faruqui-Das fine-tune
- Question retirement engine
- Provider-specific calibration tuning
