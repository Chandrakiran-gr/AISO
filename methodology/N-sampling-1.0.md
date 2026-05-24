# AISO N-Sampling and Confidence Intervals — Specification v1.0.0

**Status:** Active
**Effective from:** 2026-06-01

## Sampling parameters

| Parameter | Value | Rationale |
|---|---|---|
| N (samples per cell) | **5** | Atil et al. (arXiv:2408.04667) + Ouyang et al. (TOSEM 2025); knee in cost/precision curve |
| Temperature | **0.7** | Matches Aggarwal et al. (KDD 2024); produces genuine sampling diversity |
| top_p | **1.0** | Do not truncate model's marginal distribution |
| Per-provider seed | **hash(scan_id, question_id, provider, sample_idx) mod 2^31** | Deterministic, distinct across samples |
| Cache-bust | Inject `{"scan_id": ..., "ts": ..., "uuid": ...}` in system prompt | Prevent provider-side response caching collapsing N=5 to N=1 |

Anthropic API does not accept `seed`; rely on cache-bust UUID for entropy.

## Mandatory persistence per sample

Every sample row must record:
- `provider`, `provider_model` (e.g. `gpt-4o-2024-08-06`)
- `system_fingerprint` (OpenAI; null for others)
- `temperature`, `top_p`, `seed` (null where unsupported)
- Full request payload SHA-256
- Full raw response text (or S3 pointer if > 64 KiB)
- Raw response SHA-256
- Latency, tokens used
- Methodology version active at scan time

## Per-cell Presence interval: Wilson score

For X mentions in N samples, z = 1.96 (95%):

```
center = (X/N + z²/(2N)) / (1 + z²/N)
margin = z · √(p̂(1-p̂)/N + z²/(4N²)) / (1 + z²/N)
CI = [center - margin, center + margin]
```

Never use Wald; never use Clopper-Pearson by default.

Reference: Brown, Cai & DasGupta (Statistical Science 16(2):101-133, 2001).

## Scan-level AVS interval: nested cluster bootstrap with BCa

```
B = 10,000 (production); 2,000 (CI/CD smoke tests)
Outer resample unit: (question, provider) cluster
Inner resample unit: samples within cluster
```

BCa acceleration via jackknife over clusters. Fallback to percentile bootstrap when:
- Any sub-index ≤ 1e-9 or ≥ 1 - 1e-9
- Jackknife variance denominator < 1e-12
- BCa endpoints degenerate (a_lo not in (0, 1) or a_hi not in (0, 1))

When falling back, annotate result: `ci_method = "percentile-fallback"`.

References: Efron (JASA 1987); DiCiccio & Efron (Stat Sci 1996); Cameron, Gelbach & Miller (Restat 2008).

## Bootstrap implementation contract

```python
def nested_cluster_bootstrap(
    samples_by_pair: dict[tuple, list[Sample]],
    stance_value_map: dict[str, float],
    B: int = 10_000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, tuple[float, float], str]:
    """Returns (point_estimate, (ci_lo, ci_hi), method_used)."""
```

Method label is `"BCa"` on success, `"percentile-fallback"` on fallback. Persisted on `avs_computation.ci_method`.

## Adaptive sampling (v2, NOT IN v1)

Stage-2 adaptive: N₁=3 initial; expand to N=10 on boundary cells where mention_rate ∈ {1/3, 2/3}.

Triggered when AVS-1.1 is activated; v1.0 uses flat N=5.

## Cost economics

| N | Output tokens/scan | Provider cost @ $8/M blended | AVS bootstrap half-width estimate |
|---|---|---|---|
| 3 | 900K | ~$7 | ~5 AVS pts |
| **5** | **1.5M** | **~$12** | **~3 AVS pts** |
| 7 | 2.1M | ~$17 | ~2.5 AVS pts |
| 10 | 3.0M | ~$24 | ~2 AVS pts |

Blended cost varies with provider mix; recalibrate quarterly.

## Version bump rules

| Change | Bump |
|---|---|
| N changed | Major (sampling-2.0) — invalidates cross-scan comparison |
| Temperature changed | Major |
| CI method changed (Wilson → Bayesian; Bootstrap-BCa → Bootstrap-t) | Minor |
| B changed | Patch |
| Adaptive sampling added | Minor (sampling-1.1) |

## Limitations

1. LLM outputs are not iid Bernoulli; Wilson under-covers under batch-invariance failures. Mitigation: empirical over-dispersion audit after 50 scans.
2. Bootstrap on geometric mean unstable near zero; handled via fallback.
3. Anthropic does not expose seed; cross-provider reproducibility is asymmetric.

## References

- Brown, Cai & DasGupta (2001) — binomial interval estimation
- Efron (1987) — BCa bootstrap
- Atil et al. (2025, arXiv:2408.04667) — LLM nondeterminism
- Ouyang et al. (TOSEM 2025) — code-gen LLM consistency
- Thinking Machines Lab (Sep 2025) — batch-invariance failure
