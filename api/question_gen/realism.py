"""Application service for Phase 12 candidate realism filtering."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from api.adapters.prompt_registry import ensure_prompt_version
from api.database import QuestionCandidate
from api.domain.ports import LLMProvider
from api.domain.realism_filter import (
    REALISM_FILTER_PROMPT_KEY,
    REALISM_FILTER_PROMPT_VERSION,
    REALISM_FILTER_SYSTEM_PROMPT,
    REALISM_PASS_THRESHOLD,
    RealismEvaluation,
    evaluate_realism,
)


@dataclass(frozen=True)
class RealismFilterRun:
    evaluated_count: int
    passed_count: int
    failed_count: int
    prompt_hash: str
    prompt_version_id: str
    realism_filter_version: str
    provider: str
    model: str
    threshold: float


def apply_realism_filter(
    db: Session,
    *,
    client_id: str,
    vertical: str,
    provider: LLMProvider,
    scan_run_id: str | None = None,
    generator_version: str | None = None,
) -> RealismFilterRun:
    provider_name = str(getattr(provider, "provider", "llm"))
    model_name = str(getattr(provider, "model", "unknown"))
    prompt_row = ensure_prompt_version(
        db,
        prompt_key=REALISM_FILTER_PROMPT_KEY,
        version=REALISM_FILTER_PROMPT_VERSION,
        prompt_text=REALISM_FILTER_SYSTEM_PROMPT,
        provider=provider_name,
        model=model_name,
    )
    filter_version = f"{REALISM_FILTER_PROMPT_VERSION}:{prompt_row.prompt_hash[:12]}"

    query = db.query(QuestionCandidate).filter(QuestionCandidate.client_id == client_id)
    if scan_run_id:
        query = query.filter(QuestionCandidate.scan_run_id == scan_run_id)
    if generator_version:
        query = query.filter(QuestionCandidate.generator_version == generator_version)
    candidates = query.order_by(QuestionCandidate.created_at.asc(), QuestionCandidate.id.asc()).all()

    passed = 0
    for candidate in candidates:
        evaluation = evaluate_realism(
            question=candidate.text,
            vertical=vertical,
            provider=provider,
            idempotency_key=f"realism-filter:{client_id}:{candidate.id}:{prompt_row.prompt_hash}",
            metadata={
                "candidate_id": candidate.id,
                "journey_stage": candidate.journey_stage,
                "brand_frame": candidate.brand_frame,
                "intent_class": candidate.intent_class,
                "persona": candidate.persona,
                "locality": candidate.locality,
            },
        )
        persist_realism_evaluation(candidate, evaluation, filter_version)
        if evaluation.passed:
            passed += 1

    db.flush()
    return RealismFilterRun(
        evaluated_count=len(candidates),
        passed_count=passed,
        failed_count=len(candidates) - passed,
        prompt_hash=prompt_row.prompt_hash,
        prompt_version_id=prompt_row.id,
        realism_filter_version=filter_version,
        provider=provider_name,
        model=model_name,
        threshold=REALISM_PASS_THRESHOLD,
    )


def persist_realism_evaluation(
    candidate: QuestionCandidate,
    evaluation: RealismEvaluation,
    filter_version: str,
) -> None:
    candidate.realism_score = Decimal(f"{evaluation.realism_score:.3f}")
    candidate.realism_filter_version = filter_version
