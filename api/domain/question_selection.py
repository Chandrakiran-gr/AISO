"""Domain defaults for Phase 12 constrained question selection."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re


DEFAULT_SELECTION_TARGET_N = 50
DEFAULT_MMR_LAMBDA = 0.7
COLD_START_MMR_LAMBDA = 0.6
STEADY_STATE_MMR_LAMBDA = 0.75
SIMILARITY_THRESHOLD = 0.85
OBJECTIVE_STAGE_DEVIATION_PENALTY = 2.0
SIMILARITY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "by",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "should",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}

DEFAULT_JOURNEY_MIN: dict[str, int] = {
    "J1": 2,
    "J2": 2,
    "J3": 2,
    "J4": 2,
}

DEFAULT_FRAME_MIN: dict[str, int] = {
    "unbranded_category": 1,
    "branded_comparison": 1,
    "brand_only": 1,
    "competitor_only": 1,
}

DEFAULT_INTENT_BAND: dict[str, tuple[float, float]] = {
    "informational": (0.25, 0.55),
    "navigational": (0.05, 0.30),
    "transactional": (0.20, 0.50),
}

OBJECTIVE_STAGE_WEIGHTS: dict[str, dict[str, int]] = {
    "awareness": {"J1": 30, "J2": 35, "J3": 10, "J4": 10, "J5": 10, "J6": 5},
    "consideration": {"J1": 15, "J2": 30, "J3": 20, "J4": 20, "J5": 10, "J6": 5},
    "preference": {"J1": 5, "J2": 15, "J3": 20, "J4": 35, "J5": 20, "J6": 5},
    "reputation_defense": {"J1": 5, "J2": 10, "J3": 10, "J4": 30, "J5": 35, "J6": 10},
    "competitive_intelligence": {"J1": 10, "J2": 20, "J3": 15, "J4": 35, "J5": 15, "J6": 5},
}


@dataclass(frozen=True)
class SelectionCandidate:
    id: str
    text: str
    score: float
    journey_stage: str
    brand_frame: str
    intent_class: str
    persona: str | None = None


@dataclass(frozen=True)
class SelectionConstraints:
    target_n: int = DEFAULT_SELECTION_TARGET_N
    critical_question_ids: tuple[str, ...] = ()
    objective: str | None = None
    objective_stage_targets: dict[str, int] = field(default_factory=dict)
    journey_min: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_JOURNEY_MIN))
    frame_min: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_FRAME_MIN))
    intent_band: dict[str, tuple[float, float]] = field(default_factory=lambda: dict(DEFAULT_INTENT_BAND))
    personas: tuple[str, ...] = ()
    lambda_mmr: float = DEFAULT_MMR_LAMBDA
    similarity_threshold: float = SIMILARITY_THRESHOLD
    stage_deviation_penalty: float = OBJECTIVE_STAGE_DEVIATION_PENALTY


@dataclass(frozen=True)
class SelectionResult:
    selected_ids: list[str]
    target_n: int
    objective: str | None
    objective_stage_targets: dict[str, int]
    objective_value: float
    solver_status: str
    solver_seconds: float
    mmr_lambda: float
    high_similarity_pair_count: int
    journey_distribution: dict[str, int]
    frame_distribution: dict[str, int]
    intent_distribution: dict[str, int]
    persona_distribution: dict[str, int]


def lambda_for_mode(selection_mode: str | None) -> float:
    normalized = str(selection_mode or "default").strip().lower()
    if normalized == "cold_start":
        return COLD_START_MMR_LAMBDA
    if normalized == "steady_state":
        return STEADY_STATE_MMR_LAMBDA
    return DEFAULT_MMR_LAMBDA


def objective_stage_targets(objective: str | None, target_n: int) -> dict[str, int]:
    weights = OBJECTIVE_STAGE_WEIGHTS.get(str(objective or "").strip().lower())
    if not weights:
        return {}
    exact = {stage: (percent / 100) * target_n for stage, percent in weights.items()}
    targets = {stage: math.floor(value) for stage, value in exact.items()}
    remaining = target_n - sum(targets.values())
    ranked = sorted(
        weights,
        key=lambda stage: (exact[stage] - targets[stage], weights[stage], stage),
        reverse=True,
    )
    for stage in ranked[:remaining]:
        targets[stage] += 1
    return targets


def token_cosine_similarity(left: str, right: str) -> float:
    """Local open-source-equivalent similarity for the MMR penalty.

    It uses normalized token-frequency vectors instead of a network embedding
    call, keeping 12.8 deterministic and BYOK-safe while preserving the MIP
    contract's high-similarity pair penalty.
    """
    left_counts = _token_counts(left)
    right_counts = _token_counts(right)
    if not left_counts or not right_counts:
        return 0.0
    dot = sum(count * right_counts.get(token, 0) for token, count in left_counts.items())
    left_norm = math.sqrt(sum(count * count for count in left_counts.values()))
    right_norm = math.sqrt(sum(count * count for count in right_counts.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def distribution_for(
    candidates: list[SelectionCandidate],
    selected_ids: list[str],
    attr: str,
) -> dict[str, int]:
    selected = set(selected_ids)
    counts: dict[str, int] = {}
    for candidate in candidates:
        if candidate.id not in selected:
            continue
        value = getattr(candidate, attr)
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _token_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)?", str(text or "").lower()):
        if token in SIMILARITY_STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    return counts
