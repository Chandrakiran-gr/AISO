# AISO Question Bank — Specification v1.0.0

**Status:** Active
**Effective from:** 2026-06-01

## Core architecture

70% Core (frozen) + 30% Tail (rotating). Bridge waves required for any rotation.

| State | Behavior |
|---|---|
| **CANDIDATE** | Newly generated; not yet selected |
| **ACTIVE** | In current scan rotation |
| **FROZEN** | Core; in every scan; immutable wording |
| **TAIL** | Rotating; in scan for some period |
| **DEPRECATED** | No longer used; historical scans reference it |
| **ARCHIVED** | Permanent reference for re-aggregation under new methodology |
| **BRIDGE_IN** / **BRIDGE_OUT** | Transitional during a rotation |

## Taxonomy: (Journey Stage × Brand-Relational Frame)

Replaces the original G1–G7 taxonomy.

### Journey Stage (J1–J6)

| | Description |
|---|---|
| J1 | Problem ID / Discovery |
| J2 | Solution Exploration |
| J3 | Requirements Building |
| J4 | Supplier Selection |
| J5 | Validation |
| J6 | Post-purchase / Consensus Creation |

### Brand-Relational Frame

| | Description |
|---|---|
| U | Unbranded ("best CRM") |
| B | Brand-owned ("does [BRAND] support X") |
| C | Competitive ("[BRAND] vs [COMPETITOR]") |

### Orthogonal facets

- **Locality**: L0 global, L1 country, L2 city, L3 neighborhood
- **Persona**: P0 generic, P1+ named persona

Full question address: e.g. `J3·U·L0·P2`.

### Backward compatibility with G1–G7

| Old (G) | New (J·Frame) |
|---|---|
| G1 category/local | {J1·U, J2·U} + L1/L2 |
| G2 brand | ·B |
| G3 + G7 competitors | ·C |
| G4 transactional | J4 |
| G5 trust/reviews | J5 |
| G6 persona/occasion | Persona facet |

## Scoring rubric (11 dimensions)

| # | Dimension | Weight |
|---|---|---|
| D1 | journey_stage_match | 0.10 |
| D2 | brand_frame_match | 0.05 |
| D3 | demand_signal | 0.15 |
| D4 | commercial_proximity | 0.15 |
| D5 | buyer_plausibility | 0.10 |
| D6 | scope_calibration | 0.10 |
| D7 | objective_alignment | 0.10 |
| D8 | construct_coverage | 0.10 |
| D9 | provider_differentiation | 0.05 |
| D10 | goodhart_resistance | 0.05 |
| D11 | answer_stability | 0.05 (flag, not penalty) |
| — | diversity_penalty (MMR λ=0.7) | applied at selection |

Removed from original 12: "AI visibility opportunity" (circular with AVS).

Scorer model: Claude Sonnet 4, n=3 self-consistency. Gold scorer set: 100 hand-rated questions; required Spearman ρ ≥ 0.7 vs founder ratings.

## Lifecycle

### Cold start (scans 1–3, status=WARMUP)

Compositional template (target N=50):

| Cell | Scan 1 | Scan 4+ stable |
|---|---|---|
| J1·U | 8 | 5 |
| J2·U | 10 | 8 |
| J2·B | 4 | 6 |
| J2·C | 4 | 5 |
| J3·U | 6 | 5 |
| J4·U | 6 | 8 |
| J4·C | 4 | 6 |
| J5·B | 4 | 4 |
| J5·U / J5·C | 2 | 2 |
| J6 | 2 | 1 |

Industry-specific re-weighting allowed (B2B SaaS heavy on J2·C, J3·U, J4·C; local services heavy on J1·U·L2).

### Stabilization criteria (promote to Core)

After scan 3:
- All cells have ≥3 stable questions (mention-rate IQR < 0.2)
- Provider-by-provider PSI across scans 2→3 < 0.1 on retained questions
- Client has reviewed and approved proposed Core

Founder receives email; manual approval; bank version transitions.

### Rotation triggers

| Trigger | Tail rotation | Core touched? |
|---|---|---|
| Quarterly calendar | 25–33% of Tail | No |
| Internal PSI ≥ 0.25 on stable mention rates | 33–50% of Tail | No (flag) |
| Citation-domain PSI ≥ 0.25 | 0% — review source classifier | No |
| Client context change (small) | 10–20% of Tail | No |
| Client context change (large) | 30–50% of Tail; new Persona | Possibly — version bump |
| Provider added/replaced | 0% questions; new methodology | No |

**Never rotate >50% of Tail (15% of bank) without methodology minor bump. Never touch Core without minor bump + bridge wave.**

### Bridge wave protocol

Every rotation that removes a question runs one bridge scan with both outgoing and incoming questions present (~30% overlap per CPS ASEC 2014 precedent). Both old and new AVS computed. Dashboard shows "transitioning" badge. After bridge: outgoing → DEPRECATED; incoming → ACTIVE.

## Question weighting (Horvitz–Thompson)

```
w_q = w_journey × w_commercial × w_strategic × w_evidence
```

| Factor | Range | Notes |
|---|---|---|
| w_journey | [0.5, 2.0] | J2=1.5, J4=1.5, J3=1.2, J5=1.0, J1=0.8, J6=0.6 |
| w_commercial | [0.5, 2.0] | Industry × stage multiplier |
| w_strategic | [0.5, 3.0] | Client override; max 5 "strategic" (×2), 2 "critical" (×3) |
| w_evidence | [0.3, 1.0] | Down-weight by answer_stability |

Normalize Σ w_q = N. Applied to AVS Presence, Prominence, Positivity, CAI.

## Postgres schema

DDL (apply verbatim — referenced by execution-1.0):

```sql
CREATE TABLE question_bank_version (
    bank_version_id     UUID PRIMARY KEY,
    client_id           UUID NOT NULL,
    avs_version         TEXT NOT NULL,
    effective_from      TIMESTAMPTZ NOT NULL,
    effective_to        TIMESTAMPTZ,
    n_core              INT NOT NULL,
    n_tail              INT NOT NULL,
    n_total             INT NOT NULL,
    rotation_reason     TEXT,
    parent_version_id   UUID REFERENCES question_bank_version(bank_version_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE question (
    question_id         UUID PRIMARY KEY,
    client_id           UUID NOT NULL,
    text                TEXT NOT NULL,
    text_hash           TEXT NOT NULL,
    journey_stage       TEXT NOT NULL CHECK (journey_stage IN ('J1','J2','J3','J4','J5','J6')),
    brand_frame         TEXT NOT NULL CHECK (brand_frame IN ('U','B','C')),
    locality            TEXT NOT NULL DEFAULT 'L0',
    persona_id          UUID,
    source              TEXT NOT NULL CHECK (source IN ('generated','manual','imported')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (client_id, text_hash)
);

CREATE TABLE question_score (
    question_id         UUID NOT NULL REFERENCES question(question_id),
    scored_at           TIMESTAMPTZ NOT NULL,
    journey_match       NUMERIC(5,3),
    brand_frame_match   NUMERIC(5,3),
    demand_signal       NUMERIC(5,3),
    commercial_prox     NUMERIC(5,3),
    buyer_plausibility  NUMERIC(5,3),
    scope_calibration   NUMERIC(5,3),
    objective_alignment NUMERIC(5,3),
    construct_coverage  NUMERIC(5,3),
    provider_diff       NUMERIC(5,3),
    goodhart_resistance NUMERIC(5,3),
    answer_stability    NUMERIC(5,3),
    composite           NUMERIC(5,3) NOT NULL,
    scorer_version      TEXT NOT NULL,
    PRIMARY KEY (question_id, scored_at)
);

CREATE TABLE question_bank_membership (
    bank_version_id     UUID NOT NULL REFERENCES question_bank_version(bank_version_id),
    question_id         UUID NOT NULL REFERENCES question(question_id),
    state               TEXT NOT NULL CHECK (state IN ('FROZEN','TAIL','BRIDGE_IN','BRIDGE_OUT')),
    weight              NUMERIC(6,4) NOT NULL DEFAULT 1.0,
    entered_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (bank_version_id, question_id)
);

CREATE TABLE scan_manifest (
    scan_id             UUID NOT NULL,
    question_id         UUID NOT NULL REFERENCES question(question_id),
    bank_version_id     UUID NOT NULL REFERENCES question_bank_version(bank_version_id),
    weight_at_scan      NUMERIC(6,4) NOT NULL,
    state_at_scan       TEXT NOT NULL,
    PRIMARY KEY (scan_id, question_id)
);

CREATE TABLE question_bridge (
    bridge_id           UUID PRIMARY KEY,
    old_question_id     UUID NOT NULL REFERENCES question(question_id),
    new_question_id     UUID REFERENCES question(question_id),
    bridge_scan_id      UUID,
    equivalence_score   NUMERIC(5,3),
    bridge_method       TEXT NOT NULL CHECK (bridge_method IN ('parallel_measurement','rasch_latent','none')),
    avs_version_pre     TEXT,
    avs_version_post    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE question_deprecation (
    question_id         UUID PRIMARY KEY REFERENCES question(question_id),
    deprecated_at       TIMESTAMPTZ NOT NULL,
    reason              TEXT NOT NULL,
    replaced_by         UUID REFERENCES question(question_id)
);
```

## Invariants (enforced in application layer)

1. **Question text immutability.** Once a question has a `scan_manifest` row, its text cannot be edited. Edits must create a new `question_id` + `question_bridge` row.
2. **Bank-version monotonicity.** A scan's `bank_version_id` is set at scan-start and never changes.

## Version bump rules (applies to bank_version, separate from AVS)

| Change | Bump |
|---|---|
| Taxonomy change (replace J·Frame with something) | Major |
| Core wording change | Minor + bridge wave |
| Core added/removed | Minor + bridge wave |
| Tail rotation ≤ 33% | Patch + bridge wave |
| Tail rotation 33–50% | Minor + bridge wave |
| Scoring rubric weights | Minor (rescore archive) |

## Operational cadence

- **Weekly:** automated PSI on Core; Slack alert at PSI ≥ 0.25
- **Monthly:** founder reviews flagged context changes + candidate pool
- **Quarterly:** scheduled rotation review; client-facing change report
- **Annually:** rubric re-tuning; gold scorer set re-rated; PSI thresholds revisited

## Limitations

1. PSI thresholds 0.1 / 0.25 are heuristic from credit-risk monitoring; recalibrate after 6 months.
2. Buyer-journey research is largely B2C with B2B layer recent.
3. No published academic work addresses question-bank design for AI-visibility measurement specifically; this is an application of survey methodology + IR taxonomy to a new domain.

## References

- Schuman & Presser (1981/1996) — Questions and Answers in Attitude Surveys
- Tourangeau, Rips & Rasinski (2000) — Psychology of Survey Response
- Lemon & Verhoef (J. Marketing 2016) — Customer journey framework
- Lewis (1994) / Siddiqi (2005) — PSI thresholds
- Aggarwal et al. (KDD 2024) — GEO query categorization
- CPS ASEC 2014 redesign — bridge file precedent
