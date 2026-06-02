"""Application service for Phase 12 question scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from api.adapters.prompt_registry import ensure_prompt_version
from api.database import QuestionCandidate, QuestionScore
from api.domain.ports import BusinessProfileSnapshot, UpstreamLLMProvider
from api.domain.question_scorer import (
    QUESTION_SCORER_PROMPT_KEY,
    QUESTION_SCORER_PROMPT_VERSION,
    GWET_AC2_THRESHOLD,
    QuestionScoreInput,
    QuestionScoringEvaluation,
    ScorerAgreementError,
    score_question,
    scorer_prompt_text_for_registry,
)
from api.domain.realism_filter import REALISM_PASS_THRESHOLD


@dataclass(frozen=True)
class QuestionScorerRun:
    evaluated_count: int
    scored_count: int
    human_review_count: int
    human_review_question_ids: list[str]
    prompt_hash: str
    prompt_version_id: str
    scorer_version: str
    provider: str
    model: str
    min_gwet_ac2: float
    agreement_threshold: float


def apply_question_scorer(
    db: Session,
    *,
    client_id: str,
    snapshot: BusinessProfileSnapshot,
    provider: UpstreamLLMProvider,
    scan_run_id: str | None = None,
    generator_version: str | None = None,
    limit: int | None = None,
) -> QuestionScorerRun:
    provider_name = str(getattr(provider, "provider", "llm"))
    model_name = str(getattr(provider, "model", "unknown"))
    prompt_row = ensure_prompt_version(
        db,
        prompt_key=QUESTION_SCORER_PROMPT_KEY,
        version=QUESTION_SCORER_PROMPT_VERSION,
        prompt_text=scorer_prompt_text_for_registry(),
        provider=provider_name,
        model=model_name,
    )
    scorer_version = f"{QUESTION_SCORER_PROMPT_VERSION}:{prompt_row.prompt_hash[:12]}"

    query = db.query(QuestionCandidate).filter(QuestionCandidate.client_id == client_id)
    if scan_run_id:
        query = query.filter(QuestionCandidate.scan_run_id == scan_run_id)
    if generator_version:
        query = query.filter(QuestionCandidate.generator_version == generator_version)
    query = query.filter(QuestionCandidate.realism_score >= REALISM_PASS_THRESHOLD)
    query = query.order_by(QuestionCandidate.created_at.asc(), QuestionCandidate.id.asc())
    if limit:
        query = query.limit(limit)
    candidates = query.all()

    min_agreement = 1.0
    scored_count = 0
    human_review_question_ids: list[str] = []
    for candidate in candidates:
        try:
            evaluation = score_question(
                snapshot=snapshot,
                candidate=_candidate_input(candidate),
                provider=provider,
                idempotency_key=f"question-scorer:{client_id}:{candidate.id}:{prompt_row.prompt_hash}",
            )
        except ScorerAgreementError as exc:
            human_review_question_ids.append(candidate.id)
            flag_candidate_for_human_review(candidate, exc, scorer_version)
            min_agreement = min(min_agreement, exc.gwet_ac2)
            continue
        min_agreement = min(min_agreement, evaluation.gwet_ac2)
        persist_question_score(candidate.id, evaluation, scorer_version, db)
        scored_count += 1

    db.flush()
    return QuestionScorerRun(
        evaluated_count=len(candidates),
        scored_count=scored_count,
        human_review_count=len(human_review_question_ids),
        human_review_question_ids=human_review_question_ids,
        prompt_hash=prompt_row.prompt_hash,
        prompt_version_id=prompt_row.id,
        scorer_version=scorer_version,
        provider=provider_name,
        model=model_name,
        min_gwet_ac2=min_agreement,
        agreement_threshold=GWET_AC2_THRESHOLD,
    )


def persist_question_score(
    question_id: str,
    evaluation: QuestionScoringEvaluation,
    scorer_version: str,
    db: Session,
) -> None:
    scores = evaluation.scores
    db.add(
        QuestionScore(
            question_id=question_id,
            scored_at=datetime.now(timezone.utc),
            d1_buyer_plausibility=_decimal(scores.d1_buyer_plausibility),
            d2_commercial_proximity=_decimal(scores.d2_commercial_proximity),
            d3_cognitive_answerability=_decimal(scores.d3_cognitive_answerability),
            d4_diagnostic_power=_decimal(scores.d4_diagnostic_power),
            d5_statistical_identifiability=_decimal(scores.d5_statistical_identifiability),
            weighted_score=_decimal(evaluation.weighted_score),
            rationale=evaluation.rationale,
            scorer_version=scorer_version,
        )
    )


def flag_candidate_for_human_review(
    candidate: QuestionCandidate,
    exc: ScorerAgreementError,
    scorer_version: str,
) -> None:
    marker = (
        "[scorer_human_review_required "
        f"scorer_version={scorer_version} "
        f"gwet_ac2={exc.gwet_ac2:.3f} "
        f"threshold={exc.threshold:.3f}]"
    )
    current = str(candidate.rationale or "").strip()
    if marker not in current:
        candidate.rationale = f"{current}\n{marker}".strip()


def _candidate_input(candidate: QuestionCandidate) -> QuestionScoreInput:
    return QuestionScoreInput(
        question_id=candidate.id,
        question=candidate.text,
        journey_stage=candidate.journey_stage,
        brand_frame=candidate.brand_frame,
        intent_class=candidate.intent_class,
        persona=candidate.persona,
        locality=candidate.locality,
        rationale=candidate.rationale,
    )


def _decimal(value: float) -> Decimal:
    return Decimal(f"{value:.3f}")
