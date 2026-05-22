# AISO Upstream Pipeline — Onboarding, Question Generation, Selection — Specification v1.0.0

**Status:** Active
**Effective from:** 2026-06-01
**Supersedes:** §D.3 (11-dimension rubric) of `question-bank-1.0.md`. All other sections of `question-bank-1.0.md` remain in force.

## Architectural decision

- **Onboarding: hybrid, with mandatory founder review on every first scan for the first 100 customers.**
- **Question generation: 3× target candidate pool, vertical-conditioned prompt, realism filter, MMR deduplication, constrained selection.**
- **Question scoring: 6 dimensions (5 per-question + 1 portfolio constraint), replacing the prior 11-dimension rubric.**
- **Selection: mixed-integer programming under coverage constraints, not top-N by score.**

---

## Part A: Onboarding

### A.1 The 9-vertical taxonomy

Customer self-identifies vertical on signup. This routes the rest of the intake.

| Vertical | Code |
|---|---|
| B2B SaaS | `b2b_saas` |
| B2B Services / Agencies / Consultancies | `b2b_services` |
| Local Services (HVAC, dental, legal, plumbing, restaurants) | `local_services` |
| E-commerce / DTC | `ecommerce` |
| Regulated — Healthcare | `regulated_healthcare` |
| Regulated — Legal | `regulated_legal` |
| Regulated — Financial Advisory | `regulated_financial` |
| Consumer Brands (CPG, fashion, beauty) | `consumer_brand` |
| Marketplaces / Two-sided Platforms | `marketplace` |
| Agencies / Resellers (meta-context) | `agency` |
| Enterprise / Procurement-led | `enterprise` |

### A.2 The Minimum Context Floor

Below this floor AISO refuses to scan. Required fields by vertical:

| Vertical | Required fields |
|---|---|
| `b2b_saas` | category, ICP firmographics (industry + employee band + revenue band + geography), ACV band, 3 competitors, primary persona, primary objective, geographic scope |
| `b2b_services` | service offerings, ICP firmographics, engagement size band, 3 competitors, primary persona, geographic scope, specialization |
| `local_services` | NAP (strict format), service radius, service taxonomy, 3 local competitors, license/cert numbers, primary objective, hours |
| `ecommerce` | product categories, price tier band, target demographic, 3 brand competitors, marketplace presence, shipping geographic scope, values positioning |
| `regulated_healthcare` | specialty, jurisdictions, license numbers, HIPAA constraints, prohibited claims, primary persona, 3 competitors |
| `regulated_legal` | practice areas, jurisdictions, bar admissions, ABA Model Rule constraints, prohibited claims, primary persona, 3 competitors |
| `regulated_financial` | service type, jurisdictions, FINRA/SEC registrations, prohibited claims, primary persona, 3 competitors |
| `consumer_brand` | brand archetype, product line breadth, price tier, distribution channels, 3 competitors, demographic+psychographic target, geographic scope |
| `marketplace` | both sides' value propositions, supply taxonomy, demand ICP, 3 competing marketplaces, geographic scope, primary measurement objective |
| `agency` | client roster size, vertical distribution, AISO use case (own/client/both), if client-visibility then per-client intake using the appropriate vertical template |
| `enterprise` | B2B SaaS intake + procurement signals (SOC2/ISO 27001/FedRAMP/HIPAA), analyst recognition, reference customer logos, deployment model, buying-committee size, sales-cycle length band |

Below floor: AISO returns `400 ContextFloorNotMet` with the missing fields enumerated. Do not generate a scan.

### A.3 Crawler responsibility split

| Auto-extract (no human review needed) | Auto-extract (confirm only) | Must ask human |
|---|---|---|
| Brand name, tagline, About copy | Industry / vertical (LLM inference) | ICP (firmographics, role) |
| NAP from LocalBusiness schema | Geographic scope (sometimes in schema) | ACV / deal size band |
| Product/service taxonomy from schema | Primary vs. peripheral offerings | Top 3 competitors |
| Customer logos / case study names | — | Buyer personas / decision-makers |
| Pricing tiers (public only) | — | Strategic objective |
| Blog topic distribution | — | Regulatory / compliance constraints |
| Schema.org / JSON-LD entities | — | "Who do you lose deals to" answer |

**Crawl depth strategy:**

- **Tier 1 (always):** homepage, `/about`, `/products`|`/services`, `/pricing`, `/customers`, `/blog` index, `/robots.txt`, `/sitemap.xml`, structured data.
- **Tier 2 (if Tier 1 yields <60% confidence on profile fields):** top 20 blog posts by sitemap priority, top 5 case studies, `/careers`, Crunchbase + LinkedIn enrichment.
- **Tier 3 (enterprise/regulated only):** governance docs, security/compliance pages, jurisdictional disclaimers.

JS-rendered SPAs: use Playwright (headless Chromium) for Tier 1. Hard timeout 60 seconds.

### A.4 ICP/Persona elicitation — the 5 high-signal questions

Replace "describe your ideal customer" (which produces persona theatre) with these 5, in this order:

1. **"Name your three best customers from the last 12 months."** — AISO crawls those companies to derive observed firmographics.
2. **"Who do you lose deals to?"** — declared competitor set with loss framing.
3. **"Job title of the person who signs the contract? Job title of the person who actually uses the product day-to-day?"** — separates economic buyer from end user.
4. **"If you could get 100 more meetings booked next quarter, what kind of company would they be at?"** — forward-looking ICP without abstract persona language.
5. **"What's the one search query you wish you ranked #1 for in ChatGPT?"** — supplies a critical-question seed and reveals the customer's mental model of winning.

### A.5 Objective → composition weights

| Objective | J1 | J2 | J3 | J4 | J5 | J6 |
|---|---|---|---|---|---|---|
| Awareness building | 30% | 35% | 10% | 10% | 10% | 5% |
| Consideration | 15% | 30% | 20% | 20% | 10% | 5% |
| Preference / displacement | 5% | 15% | 20% | 35% | 20% | 5% |
| Reputation defense | 5% | 10% | 10% | 30% | 35% | 10% |
| Competitive intelligence | 10% | 20% | 15% | 35% | 15% | 5% |

These are *starting* weights. The selection algorithm enforces a minimum 2 questions per J1–J4 regardless of objective, with the objective biasing weights only for additional questions beyond the minimum.

### A.6 The v1 onboarding flow

```
1. Customer signs up (email + URL + vertical select + objective select)
2. Async crawl + LLM-drafted business profile (30–60 seconds, background)
3. Operator reviews/edits draft profile (5–10 minutes); fields flagged as "crawled" / "guessed" / "needs you"
4. Question bank generated (Part B)
5. Operator sees proposed portfolio; can flag up to 3 critical (reserved seats) and remove up to 5
6. **MANDATORY FOUNDER REVIEW** (first 100 customers): founder reviews profile + portfolio before scan kicks off
7. First-scan acceptance gate: Presence must be ≥1 for ≥60% of questions where brand is explicit subject; if fails, do not show report, route to founder
8. Promote to live; scan executes via `ScanExecutor` (see execution-1.0.md)
```

### A.7 Graduating from founder review to self-serve

Three conditions must hold simultaneously, each for 3 consecutive months:

1. Operator flag rate on generated questions <5% per scan.
2. First-scan acceptance gate passes ≥95% on first attempt.
3. LLM-judge vs human spot-check on rubric scores: Gwet AC2 ≥0.75.

Below thresholds → founder review continues. Above thresholds → automated checks + 10% sampled human review.

---

## Part B: Question Generation

### B.1 The 3× candidate pool principle

For target N (typically 50), generate 150 candidates, filter, dedupe, score, then constrained-select 50. This is the TREC analog of building larger pools than the final topic set.

### B.2 The generation system prompt (canonical, hash-chained)

```xml
<system>
You are AISO's question-generation engine. Produce a candidate pool of natural-sounding questions that real buyers might ask an LLM (ChatGPT, Claude, Perplexity, Gemini) at various stages of evaluating a category or brand. You are NOT writing SEO keywords. You are NOT writing search queries. You are writing questions in the voice of a real human typing into an AI assistant.

<inputs>
  <business_profile>{{auto_extracted_profile + customer_confirmed}}</business_profile>
  <vertical>{{one of the 9 vertical codes}}</vertical>
  <objective>{{Awareness | Consideration | Preference | Reputation_Defense | Competitive_Intelligence}}</objective>
  <competitors>{{list of named competitors}}</competitors>
  <icp>{{firmographic + persona description}}</icp>
  <geographic_scope>{{country | region | city list | radius}}</geographic_scope>
  <target_n>{{e.g., 50}}</target_n>
  <candidate_multiplier>3</candidate_multiplier>
  <vertical_pattern_library>{{10-15 patterns from §B.4}}</vertical_pattern_library>
  <constraints>
    <minimum_per_journey_stage>2</minimum_per_journey_stage>
    <minimum_per_brand_frame>1</minimum_per_brand_frame>
    <token_length_target>8-14</token_length_target>
    <forbidden_phrases>{{vertical-specific, e.g. healthcare: "cure", "guaranteed"}}</forbidden_phrases>
  </constraints>
</inputs>

<instructions>
Generate {{target_n * candidate_multiplier}} candidate questions distributed across the
(Journey Stage × Brand-Relational Frame × Persona × Locality × Intent) lattice.

For each question, output:
  - journey_stage (J1..J6)
  - brand_frame (unbranded_category | branded_comparison | brand_only | competitor_only)
  - intent_class (informational | navigational | transactional)
  - persona (which buyer role)
  - locality (if applicable)
  - rationale (one sentence: why a real buyer would ask this)

Requirements for question realism:
1. Use natural conversational syntax. A real person typing this into ChatGPT or Perplexity must look at the question and think "yes, I could see myself asking that."
2. Avoid keyword-stuffed phrasing. ("Top 10 best CRM software 2026 for small business" is keyword-stuffed; "what's the best CRM for a 50-person sales team?" is natural.)
3. Vary syntactic form: declarative ("best X"), interrogative ("how do I..."), comparative ("X vs Y"), evaluative ("is X worth..."), exploratory ("what are some...").
4. Include explicit context (industry, size, geography, use case) where a real buyer would.
5. Don't make every question include the customer's brand name. Most J1–J3 questions are unbranded.
6. Don't generate near-duplicates.
7. Vary across personas if multiple are present.
8. For competitor-named questions, name actual competitors from the input list. Don't invent.

<chain_of_thought>
Before producing the final list, think step-by-step:
1. What is the customer actually selling? Restate in one sentence.
2. Who are their three best customers' "jobs to be done" (Ulwick framing)?
3. For each journey stage J1..J6, what would a buyer in that stage realistically type?
4. For each brand-relational frame, what's a representative question?
5. Now generate the pool, biased by the objective's distribution.
</chain_of_thought>

<output_format>
Return a JSON array of {{target_n * candidate_multiplier}} objects.
No numbering. No section headers.
</output_format>
</instructions>
</system>
```

Few-shot examples per vertical are stored in `prompts/question_gen_fewshots/{vertical}.yml` and injected at runtime. Each vertical ships with 10–15 hand-written reference questions.

### B.3 The realism filter

Every candidate passes through:

```
realism_score = w1 · llm_judge_score + w2 · wellformedness_score + w3 · length_penalty
```

- **`llm_judge_score`**: Claude Sonnet 4 judges on 0–10: "On a scale of 0–10, how likely is this question to be typed verbatim (or with minor edits) by a real human buyer in {{vertical}} into ChatGPT/Perplexity?" Run n=3 self-consistency. Threshold ≥7/10.
- **`wellformedness_score`**: Probability(well-formed) from a classifier fine-tuned on the Faruqui & Das (EMNLP 2018) Paralex dataset (25,100 queries, 5-rater annotation; baseline 70.7% accuracy). **Defer to Phase 4 / Stage 4.** At v1, set `w2 = 0` and rely on LLM judge.
- **`length_penalty`**: outside 6–18 tokens, multiply by 0.5; outside 4–24, drop the question.

**Calibration target**: average realism score on held-out human-written reference set ≥0.85.

**Failure modes to detect:**

- Keyword stuffing: "Top 10 best [category] software 2026 for [industry] companies."
- Unnatural specificity: "Best CRM for B2B SaaS companies with 45–55 employees in California."
- Missing entity: "What's the best for our team?"
- Generic phrasing: "Tell me about CRM software."
- Template residue: brackets/braces still in output.

### B.4 Per-vertical pattern libraries

Each vertical ships 10–15 starter patterns. The full lists are in `prompts/question_gen_fewshots/{vertical}.yml`. Reference patterns for each vertical:

**B2B SaaS** — `best {category} for {company_size} companies in {industry}`; `{brand} vs {competitor}`; `does {brand} integrate with {tool}`; `{brand} pricing`; `{brand} reviews`; `alternatives to {brand}`.

**Local Services** — `{service} near me`; `best {service} in {city}`; `emergency {service} {city}`; `how much does {service} cost in {city}`; `{provider} reviews`.

**E-commerce** — `best {category} under ${price}`; `{brand} vs {competitor_brand}`; `is {brand} worth it`; `{brand} reviews`; `where to buy {brand}`.

**Regulated** (all sub-verticals) — all questions pass through vertical-specific compliance filter that strips prohibited claims.

(See pipeline research artifact for full pattern libraries per all 9 verticals.)

### B.5 Length distribution target

Roughly: 40% short (3–10 words) / 40% medium (10–25 words) / 20% long (25–60+ words). Enforced as a soft constraint in the selection algorithm.

### B.6 Provider-specific calibration

- **Perplexity**: rewards short focused queries (search-with-synthesis behavior). Calibrate Tail toward declarative.
- **ChatGPT / Claude**: reward longer contextualized prompts. Calibrate toward interrogative/imperative.
- **Gemini**: middle ground.

Include explicit short-form and long-form variants of the same latent need in the bank.

---

## Part C: Scoring & Selection

### C.1 The 6-dimension rubric — REPLACES the 11-dimension rubric in question-bank-1.0.md §D.3

| # | Dimension | Definition | Primary Source |
|---|---|---|---|
| **D1** | **Buyer Plausibility** | Probability a real buyer in this vertical/persona would type this (or close variant) into an LLM in the next 30 days | Broder 2002; Jansen, Booth & Spink 2008; Faruqui & Das 2018 |
| **D2** | **Commercial Proximity** | How close this question is to a revenue event | Broder 2002 (transactional class); Jansen, Booth & Spink 2008 |
| **D3** | **Cognitive Answerability** | Can the LLM parse, identify focus, retrieve context, produce stance-revealing response? | Tourangeau, Rips & Rasinski 2000; Krosnick & Presser 2010 |
| **D4** | **Diagnostic Power** | Does measuring this question produce an actionable insight? | Saracevic 1996 (situational relevance); Borlund 2003 |
| **D5** | **Statistical Identifiability** | Probability that N=5 samples produce stable Presence/Prominence reading | Voorhees 2005; Kish 1965; Saris & Gallhofer 2014 |
| **D6** | **Strategic Coverage** *(portfolio constraint, not per-question)* | Does adding this question fill an under-covered lattice slot? | Carbonell & Goldstein 1998 (MMR) |

**Weights (v1 starting values):**

```
Score_q = 0.30·D1 + 0.25·D2 + 0.20·D3 + 0.15·D4 + 0.10·D5
```

Calibrated against the 200-question gold set (§C.4).

### C.2 The scorer system prompt

Run Claude Sonnet 4 with n=3 self-consistency, gated by Gwet AC2 ≥0.75 across the 3 runs.

```xml
<system>
You are AISO's question quality scorer. For each question, score 5 dimensions on a 0–10 scale and return a JSON object. Be ruthless. Most questions should score 5–7; only exceptional questions score 8+. Score 0–3 freely on bad questions.

<inputs>
  <business_profile>{{...}}</business_profile>
  <vertical>{{...}}</vertical>
  <objective>{{...}}</objective>
  <question>{{the question to score}}</question>
  <metadata>journey_stage={{...}}, brand_frame={{...}}, intent_class={{...}}, persona={{...}}</metadata>
</inputs>

<dimensions>
  <D1 name="Buyer Plausibility">
    On 0–10, how likely is this question to be typed verbatim (or with minor edits) by a real {{persona}} buyer in {{vertical}} into ChatGPT or Perplexity in the next 30 days, given they are at the {{journey_stage}} stage?
    0 = SEO keyword bait, template residue, or unnatural phrasing.
    10 = indistinguishable from a real anonymous query in the Google/Bing log distribution.
  </D1>
  <D2 name="Commercial Proximity">
    On 0–10, how close is this question to a revenue event for the customer's business?
    10 = buyer answering this question would convert to SQL within 14 days.
    5 = research-mode but commercially relevant.
    0 = high-funnel or off-topic.
  </D2>
  <D3 name="Cognitive Answerability">
    Score 4 sub-dimensions 0–10, return mean:
    (a) Logical form: parseable structure?
    (b) Question focus: clear what's being asked?
    (c) Retrievable context: plausible LLM training data?
    (d) Stance-revealing: will response reveal Presence/Prominence/stance?
  </D3>
  <D4 name="Diagnostic Power">
    If AISO measures the customer is winning on this question, is that informative AND if losing, can they take a concrete action?
    10 = both true.
    5 = one true.
    0 = irrelevant regardless of outcome.
  </D4>
  <D5 name="Statistical Identifiability">
    Probability 5 LLM samples produce consistent Presence/Prominence reading.
    10 = specific entities, likely-deterministic LLM behavior.
    5 = moderately specific.
    0 = open-ended; 5 samples → 5 different answer structures.
  </D5>
</dimensions>

<output_format>
{
  "question_id": "...",
  "scores": {"D1": ?, "D2": ?, "D3": {"a": ?, "b": ?, "c": ?, "d": ?, "mean": ?}, "D4": ?, "D5": ?},
  "weighted_score": ?,
  "rationale": "2-3 sentences"
}
</output_format>
</system>
```

### C.3 The selection algorithm — Mixed-Integer Programming

```python
import pulp

def select_questions(candidates, target_n, constraints, λ=0.7):
    prob = pulp.LpProblem("question_selection", pulp.LpMaximize)
    x = {q.id: pulp.LpVariable(f"x_{q.id}", cat="Binary") for q in candidates}

    # Linearize pairwise similarity penalty
    high_sim_pairs = [(i, j) for i in candidates for j in candidates
                      if i.id < j.id and cosine_sim(i.emb, j.emb) > 0.85]
    sim_vars = {(i.id, j.id): pulp.LpVariable(f"sim_{i.id}_{j.id}", cat="Binary")
                for i, j in high_sim_pairs}
    for (i, j), v in sim_vars.items():
        prob += v >= x[i] + x[j] - 1

    prob += (pulp.lpSum(q.score * x[q.id] for q in candidates)
             - λ * pulp.lpSum(sim_vars.values()))

    prob += pulp.lpSum(x.values()) == target_n
    for cq in constraints.critical_question_ids:
        prob += x[cq] == 1
    for j_stage, min_count in constraints.journey_min.items():
        prob += pulp.lpSum(x[q.id] for q in candidates if q.journey_stage == j_stage) >= min_count
    for frame, min_count in constraints.frame_min.items():
        prob += pulp.lpSum(x[q.id] for q in candidates if q.brand_frame == frame) >= min_count
    for intent, (lo, hi) in constraints.intent_band.items():
        s = pulp.lpSum(x[q.id] for q in candidates if q.intent_class == intent)
        prob += s >= lo * target_n
        prob += s <= hi * target_n
    for persona in constraints.personas:
        prob += pulp.lpSum(x[q.id] for q in candidates if q.persona == persona) >= 1

    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    return [q for q in candidates if pulp.value(x[q.id]) > 0.5]
```

Solver: `pulp.PULP_CBC_CMD` (free, ships with `pip install pulp`). For larger N, swap in Gurobi.

### C.4 The 200-question gold set

**Construction:**

- 200 hand-rated questions, ~22 per vertical.
- Each rated by founder + 2 expert raters on 0–10 ("would this question be useful in an AISO scan for a real customer in this vertical?")
- Inter-rater Gwet AC2 must reach ≥0.75 — discuss and re-rate disagreements until convergence.
- Stratified: 50 obvious good, 50 obvious bad, 100 borderline.

**Validation procedure:**

1. Run new 6-dimension scorer on all 200 questions.
2. Compute Pearson and Spearman correlation vs gold-set mean rating.
3. **Acceptance:** Spearman ρ ≥0.65 on held-out test (60/40 train/test).
4. If fails: re-fit weights via constrained linear regression (sum to 1, all ≥0.05) to maximize Spearman on training.
5. Compare against old 11-dimension rubric on same 200 questions. **New must beat old by ≥0.10 in Spearman ρ.**
6. Report per-vertical Spearman ρ.

### C.5 The right N per scan

| Scan tier | N | Rationale |
|---|---|---|
| Cold-start (first scan) | 50 | Coverage-heavy; establishes baseline |
| Steady-state recurring | 35–45 | Exploitation-biased; retire low-discrimination |
| Enterprise deep-scan | 80–120 | More personas, localities, competitors |
| Quick-pulse | 20 | Top-discriminating watchlist |

Derivation grounded in Voorhees 2005 (TREC ~50 topics convention), Fleiss 1973 paired-comparison power calculation, and lattice coverage requirements. See pipeline research artifact for full derivation.

### C.6 Cold-start vs steady-state selection

**Cold-start (scans 1–3):**

- Exploration-heavy.
- λ_MMR = 0.6 (higher diversity weight).
- All 5 dimensions weighted as in §C.1.
- Statistical Identifiability is heuristic only.

**Steady-state (scans 4+):**

- Exploitation-biased.
- λ_MMR = 0.75.
- Statistical Identifiability uses empirical Wilson CI widths from prior scans.
- **Question retirement:** retire if <2-point Presence variance over last 5 scans OR competitive landscape shifted enough to rebalance journey-stage distribution.

### C.7 Post-scan diagnostics (feed back to selection)

Three set-level properties move *out* of per-question scoring and *into* post-scan diagnostics:

- **Provider differentiation** (from old D9): per-question variance of Presence/Prominence across providers; computed after each scan; questions with σ < 0.10 across all providers are candidates for retirement (no signal).
- **Answer stability** (from old D11): empirical Wilson CI width on Presence per question, across scans; feeds into D5 prior for next scan.
- **Goodhart resistance** (from old D10): system-level monitoring; spike in mention rate for any question >2σ above 90-day baseline triggers human review (possible gaming).

---

## Postgres schema additions

```sql
CREATE TABLE business_profile (
    client_id           UUID PRIMARY KEY REFERENCES clients(id),
    vertical            TEXT NOT NULL CHECK (vertical IN (
        'b2b_saas','b2b_services','local_services','ecommerce',
        'regulated_healthcare','regulated_legal','regulated_financial',
        'consumer_brand','marketplace','agency','enterprise'
    )),
    objective           TEXT NOT NULL CHECK (objective IN (
        'awareness','consideration','preference','reputation_defense','competitive_intelligence'
    )),
    category            TEXT NOT NULL,
    icp                 JSONB NOT NULL,
    geographic_scope    JSONB NOT NULL,
    competitors         TEXT[] NOT NULL,
    personas            JSONB NOT NULL,
    crawl_artifacts     JSONB NOT NULL,
    onboarding_completed_at TIMESTAMPTZ,
    founder_reviewed_at TIMESTAMPTZ,
    floor_met           BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE question_candidate (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           UUID NOT NULL REFERENCES clients(id),
    scan_run_id         UUID,
    text                TEXT NOT NULL,
    text_hash           TEXT NOT NULL,
    journey_stage       TEXT NOT NULL,
    brand_frame         TEXT NOT NULL,
    intent_class        TEXT NOT NULL,
    persona             TEXT,
    locality            TEXT,
    rationale           TEXT,
    realism_score       NUMERIC(5,3),
    selected            BOOLEAN NOT NULL DEFAULT false,
    generator_version   TEXT NOT NULL,
    realism_filter_version TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (client_id, text_hash, generator_version)
);

CREATE TABLE question_score (
    question_id         UUID NOT NULL REFERENCES question_candidate(id),
    scored_at           TIMESTAMPTZ NOT NULL,
    d1_buyer_plausibility       NUMERIC(5,3),
    d2_commercial_proximity     NUMERIC(5,3),
    d3_cognitive_answerability  NUMERIC(5,3),
    d4_diagnostic_power         NUMERIC(5,3),
    d5_statistical_identifiability NUMERIC(5,3),
    weighted_score              NUMERIC(5,3) NOT NULL,
    rationale                   TEXT,
    scorer_version              TEXT NOT NULL,
    PRIMARY KEY (question_id, scored_at)
);
```

## Version bump rules (composes with question-bank-1.0 versioning)

| Change | Bump |
|---|---|
| Add/remove dimension | Major (pipeline-2.0) |
| Weight tweak | Minor (pipeline-1.1) |
| Few-shot library refresh | Minor |
| New vertical added | Minor |
| Generation prompt edit | Minor (re-hash, re-version) |
| Realism filter threshold change | Minor |
| Selection algorithm change | Minor |
| Compliance filter update | Patch |

Every prompt and weight change goes through the bitemporal versioning pipeline (`versioning-1.0.md`).

## Limitations

1. The 200-question gold set is the most labor-intensive single piece; budget 2 weeks of founder + 2 contractor raters.
2. Faruqui & Das classifier is deferred to Stage 4 (post-launch).
3. The 6-dimension rubric is a design proposal; validation cycle in §C.4 must pass before claiming improvement.
4. Cold-start vs steady-state branching presumes ≥3 scans of history; v1 ships only cold-start logic.
5. Multi-turn (CAsT-style) question probes are out of v1 scope; v2 candidate.
6. Regulated vertical compliance filters are sketched, not built; requires attorney review before serving healthcare/legal/financial customers.

## References

- Broder, "A Taxonomy of Web Search" (*SIGIR Forum* 36(2), 2002)
- Jansen, Booth & Spink, "Determining the informational, navigational, and transactional intent of Web queries" (*Information Processing & Management* 44(3), 2008)
- Tourangeau, Rips & Rasinski, *The Psychology of Survey Response* (Cambridge UP, 2000)
- Krosnick & Presser, "Question and Questionnaire Design," in *Handbook of Survey Research* 2nd ed. (Emerald, 2010)
- Saris & Gallhofer, *Design, Evaluation, and Analysis of Questionnaires for Survey Research* 2nd ed. (Wiley, 2014)
- Voorhees, "Overview of the TREC 2004 Robust Retrieval Track" (*SIGIR Forum* 39(1), 2005)
- Voorhees & Buckley, "The Effect of Topic Set Size on Retrieval Experiment Error" (SIGIR 2002)
- Saracevic, "Relevance reconsidered" (CoLIS 2, 1996)
- Carbonell & Goldstein, "The Use of MMR, Diversity-Based Reranking for Reordering Documents and Producing Summaries" (SIGIR 1998)
- Faruqui & Das, "Identifying Well-Formed Natural Language Questions" (EMNLP 2018)
- Adamson et al. (Gartner), "The B2B Buying Journey," updated 2024
- Lemon & Verhoef, "Understanding Customer Experience Throughout the Customer Journey" (*Journal of Marketing* 80(6), 2016)
- Revella, *Buyer Personas* (Wiley, 2015) — 5 Rings of Buying Insight
- Ulwick, *Jobs to Be Done: Theory to Practice* (Idea Bite Press, 2016) — ODI framework
- Rennie & Protheroe (Think with Google), *Decoding Decisions: Making Sense of the Messy Middle* (2020)
- Kish, *Survey Sampling* (Wiley, 1965) — design effects
- Fleiss, *Statistical Methods for Rates and Proportions* (Wiley, 1973)
