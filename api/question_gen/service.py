"""Application service for generating and persisting candidate questions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

from sqlalchemy.orm import Session

from api.adapters.prompt_registry import ensure_prompt_version
from api.database import Client, QuestionCandidate
from api.domain.ports import BusinessProfileSnapshot, UpstreamLLMProvider
from api.domain.question_generation import (
    QUESTION_GENERATION_PROMPT_KEY,
    QUESTION_GENERATION_PROMPT_VERSION,
    QUESTION_GENERATION_SYSTEM_PROMPT,
    REALISM_FILTER_PENDING_VERSION,
    GeneratedQuestionCandidate,
    brand_frame_distribution,
    candidate_pool_size,
    context_from_snapshot,
    distribution_for_candidates,
    generate_question_candidates,
    question_text_hash,
)
from api.question_gen.fewshots import load_vertical_fewshots


@dataclass(frozen=True)
class PersistedQuestionGenerationRun:
    candidates: list[QuestionCandidate]
    prompt_hash: str
    prompt_version_id: str
    generator_version: str
    provider: str
    model: str
    distribution: dict[str, int]
    brand_frame_distribution: dict[str, int]


def generate_and_persist_question_candidates(
    db: Session,
    *,
    client: Client,
    snapshot: BusinessProfileSnapshot,
    provider: UpstreamLLMProvider,
    target_n: int = 50,
    scan_run_id: str | None = None,
) -> PersistedQuestionGenerationRun:
    fewshots = load_vertical_fewshots(snapshot.vertical)
    context = context_from_snapshot(
        snapshot,
        brand_name=client.name,
        target_n=target_n,
        fewshot_examples=fewshots,
    )
    provider_name = str(getattr(provider, "provider", "llm"))
    model_name = str(getattr(provider, "model", "unknown"))
    prompt_row = ensure_prompt_version(
        db,
        prompt_key=QUESTION_GENERATION_PROMPT_KEY,
        version=QUESTION_GENERATION_PROMPT_VERSION,
        prompt_text=QUESTION_GENERATION_SYSTEM_PROMPT,
        provider=provider_name,
        model=model_name,
    )
    result = generate_question_candidates(
        context,
        provider,
        idempotency_key=(
            f"question-generation:{snapshot.client_id}:{prompt_row.prompt_hash}:"
            f"{target_n}:{scan_run_id or 'cold-start'}"
        ),
    )
    generator_version = f"{QUESTION_GENERATION_PROMPT_VERSION}:{prompt_row.prompt_hash[:12]}"
    persisted = _persist_candidates(
        db,
        client_id=snapshot.client_id,
        scan_run_id=scan_run_id,
        candidates=result.candidates,
        generator_version=generator_version,
    )
    if len(persisted) != candidate_pool_size(target_n):
        raise ValueError("Question generation did not persist the requested candidate pool size")

    return PersistedQuestionGenerationRun(
        candidates=persisted,
        prompt_hash=prompt_row.prompt_hash,
        prompt_version_id=prompt_row.id,
        generator_version=generator_version,
        provider=result.provider_response.provider,
        model=result.provider_response.model,
        distribution=distribution_for_candidates(result.candidates),
        brand_frame_distribution=brand_frame_distribution(result.candidates),
    )


def _persist_candidates(
    db: Session,
    *,
    client_id: str,
    scan_run_id: str | None,
    candidates: list[GeneratedQuestionCandidate],
    generator_version: str,
) -> list[QuestionCandidate]:
    persisted: list[QuestionCandidate] = []
    now = datetime.now(timezone.utc)
    for candidate in candidates:
        text_hash = question_text_hash(candidate.text)
        existing = db.query(QuestionCandidate).filter(
            QuestionCandidate.client_id == client_id,
            QuestionCandidate.text_hash == text_hash,
            QuestionCandidate.generator_version == generator_version,
        ).first()
        if existing:
            existing.scan_run_id = scan_run_id
            existing.journey_stage = candidate.journey_stage
            existing.brand_frame = candidate.brand_frame
            existing.intent_class = candidate.intent_class
            existing.persona = candidate.persona
            existing.locality = candidate.locality
            existing.rationale = candidate.rationale
            row = existing
        else:
            row = QuestionCandidate(
                id=str(uuid.uuid4()),
                client_id=client_id,
                scan_run_id=scan_run_id,
                text=candidate.text,
                text_hash=text_hash,
                journey_stage=candidate.journey_stage,
                brand_frame=candidate.brand_frame,
                intent_class=candidate.intent_class,
                persona=candidate.persona,
                locality=candidate.locality,
                rationale=candidate.rationale,
                selected=False,
                generator_version=generator_version,
                realism_filter_version=REALISM_FILTER_PENDING_VERSION,
                created_at=now,
            )
            db.add(row)
        persisted.append(row)
    db.flush()
    return persisted
