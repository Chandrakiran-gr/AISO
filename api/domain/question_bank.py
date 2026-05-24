"""Question-bank mapping and weighting rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


BANK_FRAME_UNBRANDED = "U"
BANK_FRAME_BRAND = "B"
BANK_FRAME_COMPARISON = "C"
QUESTION_BANK_AVS_VERSION = "AVS-1.0.0"
QUESTION_BANK_INITIAL_CORE_RATIO = Decimal("0.70")
QUESTION_BANK_MAX_STRATEGIC = 5
QUESTION_BANK_MAX_CRITICAL = 2

PHASE12_TO_BANK_BRAND_FRAME = {
    "unbranded_category": BANK_FRAME_UNBRANDED,
    "brand_only": BANK_FRAME_BRAND,
    "branded_comparison": BANK_FRAME_COMPARISON,
    "competitor_only": BANK_FRAME_COMPARISON,
}

JOURNEY_WEIGHT_MULTIPLIERS = {
    "J1": Decimal("0.8"),
    "J2": Decimal("1.5"),
    "J3": Decimal("1.2"),
    "J4": Decimal("1.5"),
    "J5": Decimal("1.0"),
    "J6": Decimal("0.6"),
}


@dataclass(frozen=True)
class QuestionWeightInput:
    question_id: str
    journey_stage: str
    brand_frame: str
    locality: str | None = None
    vertical: str | None = None
    answer_stability: Decimal | int | float | str | None = None
    strategic: bool = False
    critical: bool = False


def canonical_brand_frame(phase12_brand_frame: str) -> str:
    try:
        return PHASE12_TO_BANK_BRAND_FRAME[phase12_brand_frame]
    except KeyError as exc:
        raise ValueError(f"Unsupported Phase 12 brand_frame: {phase12_brand_frame}") from exc


def initial_core_count(total_questions: int) -> int:
    return int((Decimal(total_questions) * QUESTION_BANK_INITIAL_CORE_RATIO).to_integral_value(rounding=ROUND_HALF_UP))


def raw_question_weight(question: QuestionWeightInput) -> Decimal:
    return (
        journey_weight(question.journey_stage)
        * commercial_weight(question.vertical, question.journey_stage, question.brand_frame, question.locality)
        * strategic_weight(strategic=question.strategic, critical=question.critical)
        * evidence_weight(question.answer_stability)
    )


def journey_weight(journey_stage: str) -> Decimal:
    return JOURNEY_WEIGHT_MULTIPLIERS.get(journey_stage, Decimal("1.0"))


def commercial_weight(
    vertical: str | None,
    journey_stage: str,
    brand_frame: str,
    locality: str | None,
) -> Decimal:
    normalized_vertical = str(vertical or "").strip().lower().replace("-", "_")
    locality_level = _locality_level(locality)

    if normalized_vertical in {"b2b_saas", "saas", "software"}:
        if (journey_stage, brand_frame) in {
            ("J2", BANK_FRAME_COMPARISON),
            ("J3", BANK_FRAME_UNBRANDED),
            ("J4", BANK_FRAME_COMPARISON),
        }:
            return Decimal("1.25")

    if normalized_vertical in {"local_services", "local_service", "local"}:
        if journey_stage == "J1" and brand_frame == BANK_FRAME_UNBRANDED and locality_level >= 2:
            return Decimal("1.25")

    return Decimal("1.0")


def strategic_weight(*, strategic: bool, critical: bool) -> Decimal:
    if critical:
        return Decimal("3.0")
    if strategic:
        return Decimal("2.0")
    return Decimal("1.0")


def evidence_weight(answer_stability: Decimal | int | float | str | None) -> Decimal:
    if answer_stability is None:
        return Decimal("1.0")
    try:
        stability = Decimal(str(answer_stability))
    except (InvalidOperation, ValueError):
        return Decimal("1.0")
    if stability > 1:
        stability = stability / Decimal("10")
    stability = min(max(stability, Decimal("0")), Decimal("1"))
    return Decimal("0.3") + (Decimal("0.7") * stability)


def normalized_question_weights(
    questions: list[QuestionWeightInput],
    *,
    target_total: int,
) -> list[Decimal]:
    if not questions:
        return []

    critical_count = sum(1 for question in questions if question.critical)
    strategic_count = sum(1 for question in questions if question.strategic)
    if critical_count > QUESTION_BANK_MAX_CRITICAL:
        raise ValueError("At most 2 critical question weight overrides are allowed")
    if strategic_count > QUESTION_BANK_MAX_STRATEGIC:
        raise ValueError("At most 5 strategic question weight overrides are allowed")

    raw_weights = [raw_question_weight(question) for question in questions]
    raw_total = sum(raw_weights, Decimal("0"))
    if raw_total <= 0:
        raise ValueError("Question-bank weights must have a positive total")
    quant = Decimal("0.0001")
    normalized = [
        (weight * Decimal(target_total) / raw_total).quantize(quant, rounding=ROUND_HALF_UP)
        for weight in raw_weights
    ]
    drift = Decimal(target_total).quantize(quant) - sum(normalized, Decimal("0"))
    normalized[-1] = (normalized[-1] + drift).quantize(quant, rounding=ROUND_HALF_UP)
    return normalized


def normalized_journey_weights(journey_stages: list[str], *, target_total: int) -> list[Decimal]:
    return normalized_question_weights(
        [
            QuestionWeightInput(
                question_id=str(index),
                journey_stage=stage,
                brand_frame=BANK_FRAME_UNBRANDED,
            )
            for index, stage in enumerate(journey_stages)
        ],
        target_total=target_total,
    )


def _locality_level(locality: str | None) -> int:
    value = str(locality or "").strip().upper()
    if value.startswith("L") and value[1:].isdigit():
        return int(value[1:])
    return 0
