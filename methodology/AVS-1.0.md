# AISO Visibility Score (AVS) — Specification v1.0.0

**Status:** Active
**Effective from:** 2026-06-01
**Previous version:** None (initial)

## Normative formula

```
AVS = 100 · (Presence · Prominence · Positivity)^(1/3)
```

Geometric mean of three sub-indices, each normalized to [0, 1]. AVS reports on [0, 100].

A parallel **Citation Authority Index (CAI)** is reported for grounded responses only:
```
CAI = 100 · (Coverage · Authority · Recency)^(1/3)
```

CAI is reported alongside AVS, never blended into it.

## Sub-index definitions

### Presence ∈ [0, 1]

Per (question q, provider p) cell: `mention_rate(q,p) = mentions / N`
where N is the sample count and `mentions` is the count of samples in which the
brand is mentioned (verbatim or via canonical alias).

Scan-level Presence:
```
Presence = (1/|Q|·|P|) · Σ_{q,p} mention_rate(q, p)
```

### Prominence ∈ [0, 1]

Per (question, provider, sample) using PAWC-style exponential decay
(Aggarwal et al., KDD 2024):

```
prominence_score(s) = e^(-pos(s) / |S|)
```

where `pos(s)` is 1-indexed position of the first mention in sample `s` and
`|S|` is the number of "ranked items" in `s` (sentences if no list; list items if structured).

Cell aggregate: mean over mentioning samples.
Scan aggregate: mean over (q, p) cells. Cells with zero mentions contribute 0.

### Positivity ∈ [0, 1]

Six-level stance taxonomy with numeric values:

| Label | Meaning | Numeric value |
|---|---|---|
| R+ | Recommended FOR | 1.00 |
| C+ | Comparative positive / listed favorably | 0.75 |
| N | Neutral mention | 0.50 |
| C− | Comparative negative | 0.25 |
| F− | Factual negative (outage, lawsuit) | 0.10 |
| R− | Recommended AGAINST | 0.00 |

Per-sample Positivity = position-weighted mean stance:
```
positivity(s) = Σ_m (w(m) · v(σ(m))) / Σ_m w(m)
```
where `w(m) = e^(-pos(m)/|S|)`, `σ(m)` is the stance label, `v(·)` is the value map.

Scan aggregate: mean over mentioning samples; non-mentioning samples omitted (not zero-imputed).

## Sampling parameters (must come from sampling_config_version)

- N = 5 per (question, provider) cell
- Temperature = 0.7
- Distinct integer seeds per sample: `seed = hash(scan_id, question_id, provider, sample_idx) mod 2^31`
- See `N-sampling-1.0.md` for full sampling specification.

## Confidence intervals (must come from sampling_config_version)

- **Per-cell Presence:** Wilson 95% score interval.
- **Scan-level AVS, sub-indices, CAI:** nested cluster bootstrap with BCa, B=10,000.
- See `N-sampling-1.0.md` §B for full CI specification.

## Version bump rules

| Change | Bump |
|---|---|
| Sub-index added or removed | Major (AVS-2.0) |
| Aggregation function change (geometric → arithmetic) | Major |
| Sub-index formula change (e.g., new position weighting) | Minor (AVS-1.1) |
| Stance taxonomy expansion (7-level) | Minor |
| Stance value map change | Minor |
| Constant tweak (numerator constant 100 → 1000) | Minor |
| Documentation clarification | Patch (AVS-1.0.1) |

## Edge cases

- **Zero mentions across entire scan**: AVS = 0 exactly; bootstrap CI not informative; report annotation required.
- **Single provider returns zero samples**: report `partial_degraded`; AVS computed cross-provider only.
- **AVS computation under partial completion**: AVS is robust to missing samples when ≥3 per cell remain.

## Worked example

Q=50, P=4, N=5; scan-level Presence = 0.42, Prominence = 0.55, Positivity = 0.68:
```
AVS = 100 · (0.42 · 0.55 · 0.68)^(1/3) = 100 · 0.157^(1/3) = 100 · 0.540 = 54.0
```

Bootstrap 95% CI (B=10,000, BCa): [51.2, 56.8].

## Cross-references

- Sampling: `N-sampling-1.0.md`
- Stance + source classification: `classifier-1.0.md`
- Question bank composition: `question-bank-1.0.md`
- Persistence + audit: `versioning-1.0.md`
- Execution: `execution-1.0.md`

## Limitations

1. Geometric-mean composite is dominated by smallest factor (intentional — penalizes blind spots).
2. Bootstrap CI degenerates near AVS = 0; fallback to percentile bootstrap; annotate report.
3. Stance value map (R+=1.0, C+=0.75, etc.) is a chosen ordinal scale, not an empirically-validated cardinal one. Treat as Likert-with-distance, not as interval.

## References

- Aggarwal et al. (KDD 2024) — PAWC formulation
- Brown, Cai & DasGupta (Stat Sci 2001) — Wilson interval rationale
- Efron (JASA 1987) — BCa bootstrap
- HDI/UNDP (2010) — geometric mean composite precedent
