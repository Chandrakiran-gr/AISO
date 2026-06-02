# AISO Hybrid Classifier — Specification v1.0.0

**Status:** Active
**Effective from:** 2026-06-01

Two classifiers feed AVS-1.0:
1. **Stance classifier** → Positivity sub-index (six-level ordinal)
2. **Source classifier** → CAI (six-class nominal)

## Stance classifier

### Model and parameters

| Parameter | Value | Rationale |
|---|---|---|
| Judge model | **Claude Sonnet 4** | Cross-family vs measured providers (avoids self-enhancement bias) |
| Temperature | **0.3** | Stance is more discrete than open-ended QA |
| Self-consistency n | **3** | Wang et al. (ICLR 2023) self-consistency pattern |
| Aggregation | **Majority label; agreement count is discrete confidence signal** | Verbalized confidence is overconfident per Geng et al. (NAACL 2024) |
| Prompt caching | **Enabled on rubric block** | Anthropic prompt caching, ~10% cost on cache reads |
| Window | **±200 tokens** around mention | Reduce verbosity bias |

### Output contract

```python
@dataclass
class StanceResult:
    label: Literal["R+", "C+", "N", "C-", "F-", "R-"]
    agreement_count: int  # 1, 2, or 3 out of n=3
    individual_judgments: list[str]  # raw outputs of n=3 calls
    confidence: float  # mapped via 3-bin calibration table; refit monthly
```

### Prompt template (canonical)

See `classifier-1.0/stance_prompt.txt` for the verbatim system prompt + 12 few-shot examples. The system prompt MUST be hashed (SHA-256) and the hash MUST be recorded on every classification row.

### Critical distinctions in the rubric

- Stance is toward TARGET, not generic sentiment.
- Sarcasm reverses surface polarity.
- Hedging weakens stance.
- Listing in a top-N without commentary is C+, not R+.

### Per-mention cost (Sonnet 4 @ $3/$15 per 1M tokens, n=3, cached)

≈ **$0.0027 per mention**. At ~750 mentions per scan: **~$2.03 cold / ~$1.40 warm**.

## Source classifier

### Architecture

1. eTLD+1 extraction via Public Suffix List (`tldextract` or `publicsuffix2`).
2. Postgres lookup in `domain_classification` table.
3. Cache miss → LLM judge fallback (Claude Sonnet 4, single-shot).
4. Result written back with 90-day TTL.

### Classes

```
OWNED       — client-controlled property (pre-supplied)
EARNED-HIGH — .gov, .gov.uk, .edu, Wikipedia, tier-1 press, peer-reviewed
EARNED-MID  — trade press, mid-tier business, review aggregators
UGC         — Reddit, Quora, forums, Q&A, blog platforms, social, video
COMPETITOR  — client-declared competitor (pre-supplied)
UNKNOWN     — indeterminate; LLM fallback ran
```

### Seed list

~200 domains across EARNED-HIGH, EARNED-MID, UGC, and platform-private suffixes (github.io, blogspot.com, etc.). See `classifier-1.0/source_seed.json`.

### Per-client overrides

Loaded at scan time from `client.owned_domains` and `client.competitor_domains`. Override the static map.

### Per-domain LLM fallback cost

~$0.007 per unknown domain. After warming, ~50–100 misses/scan; budget ~$0.35/scan cold, ~$0.05/scan warm.

## Inter-rater agreement (IRR) — gating metric

### Primary metric: Gwet's AC2

Quadratic-weighted, ordinal scale (R-, F-, C-, N, C+, R+) mapped to (1..6).

Rationale: Bloomberg Law LLM-as-judge (arXiv:2509.12382) finds AC2 robust under skewed class distributions where Cohen's κ / Krippendorff's α collapse (kappa paradox; Feinstein & Cicchetti 1990).

### Deployment gates

| Metric | Threshold | Action if fail |
|---|---|---|
| Stance AC2 (quadratic-weighted) | **≥ 0.75** | Block release |
| Source AC1 (categorical) | **≥ 0.80** | Block release |
| Per-class recall for R+, R-, F- (stance) | **≥ 0.70** | Block release |
| Per-class recall for all stance classes | **≥ 0.60** | Block release |

### Gold-set construction (DEFERRED to post-v1)

- 200-item stratified gold set, refreshed 50 items/quarter
- 3 raters (2 contractor + founder adjudication)
- Year-1 cost: ~$1,500

## Drift monitoring (DEFERRED to post-v1 except for the schema)

| Metric | Baseline | Threshold | Action |
|---|---|---|---|
| Stance class PSI per provider | rolling 30-day | > 0.2 | Page founder; investigate |
| Source class PSI per provider | rolling 30-day | > 0.2 | Page founder; investigate |
| UNKNOWN-rate per scan/provider | rolling 7-day median | > 2σ for 3 consecutive days | Backfill static map |
| Self-consistency 3/3 rate | rolling 30-day | drop > 10pp | Investigate judge |
| Gold-set AC2 (stance) | 0.75 floor | < 0.70 | Block release |
| Source cache hit rate | rolling 7-day | < 60% | Refresh seed list |

PSI thresholds: < 0.1 (stable) / 0.1–0.25 (watch) / ≥ 0.25 (act). Source: Lewis (1994) / Siddiqi (2005).

## Confidence propagation into AVS

3-bin calibration table maps agreement count → confidence:
- 3/3 → c₃ (typically ~0.95)
- 2/3 → c₂ (typically ~0.75)
- 1/1/1 → c₁ (typically ~0.40)

Refit monthly against gold set.

Confidence-weighted Positivity:
```
Positivity_conf = Σ_s c(s)·w(s)·v(σ(s)) / Σ_s c(s)·w(s)
```

Bootstrap CI: resample classifier labels in inner loop, weighted by confidence.

## Version bump rules

| Change | Bump |
|---|---|
| Judge model family change (Sonnet 4 → Llama 3.1 70B) | Major (classifier-2.0) |
| Prompt rubric structural change | Minor (classifier-1.1) |
| Few-shot anchor refresh | Minor |
| Self-consistency n change (3 → 5) | Minor |
| Gold-set refresh | Patch (classifier-1.0.1) |
| Calibration table refit | Patch |

## Limitations

1. Multi-class ordinal LLM-as-judge agreement under-studied for 6-class.
2. Self-enhancement bias is documented theory; effect size in AISO's specific setup is unmeasured.
3. AC2 robustness in AI-evaluation context has only Bloomberg (2025) as primary citation.

## References

- Zheng et al. (NeurIPS 2023, arXiv:2306.05685) — LLM-as-judge with MT-Bench
- Liu et al. (EMNLP 2023, arXiv:2303.16634) — G-Eval
- Wang et al. (arXiv:2305.17926) — "LLMs are not Fair Evaluators"
- Wang et al. (ICLR 2023, arXiv:2203.11171) — Self-Consistency
- Geng et al. (NAACL 2024, arXiv:2311.08298) — LLM confidence calibration survey
- Gwet (2014) — Handbook of Inter-Rater Reliability
- Pradhan et al. (arXiv:2509.12382) — Bloomberg Law LLM-as-judge
