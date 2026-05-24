"""Import Phase 12 selected questions into the canonical question bank."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import uuid

from sqlalchemy.orm import Session

from api.database import (
    QuestionBankMembership,
    QuestionBankQuestion,
    QuestionBankScore,
    QuestionBankVersion,
    QuestionCandidate,
    QuestionScore,
    ScanManifest,
)
from api.domain.question_bank import (
    QUESTION_BANK_AVS_VERSION,
    QuestionWeightInput,
    canonical_brand_frame,
    initial_core_count,
    normalized_question_weights,
)
from api.domain.question_generation import question_text_hash


class QuestionBankImportError(ValueError):
    """Raised when selected questions cannot be imported into the question bank."""


@dataclass(frozen=True)
class QuestionBankImportResult:
    bank_version_id: str
    question_count: int
    manifest_count: int
    n_core: int
    n_tail: int
    weight_sum: Decimal


def import_selected_questions_to_question_bank(
    db: Session,
    *,
    client_id: str,
    scan_id: str,
    selected_at: datetime,
    rows: list[tuple[QuestionCandidate, QuestionScore]],
    vertical: str | None = None,
    strategic_question_ids: set[str] | None = None,
    critical_question_ids: set[str] | None = None,
) -> QuestionBankImportResult:
    if not rows:
        raise QuestionBankImportError("Question-bank import requires selected questions")

    existing_manifest = (
        db.query(ScanManifest)
        .filter(ScanManifest.scan_id == scan_id)
        .order_by(ScanManifest.question_id.asc())
        .all()
    )
    if existing_manifest:
        expected_question_ids = {
            _canonical_question_id(client_id, candidate)
            for candidate, _ in rows
        }
        existing_question_ids = {row.question_id for row in existing_manifest}
        bank_version_ids = {row.bank_version_id for row in existing_manifest}
        if (
            len(existing_manifest) != len(rows)
            or len(bank_version_ids) != 1
            or existing_question_ids != expected_question_ids
        ):
            raise QuestionBankImportError("Existing scan manifest does not match selected question portfolio")
        bank_version_id = next(iter(bank_version_ids))
        version = (
            db.query(QuestionBankVersion)
            .filter(QuestionBankVersion.bank_version_id == bank_version_id)
            .one()
        )
        return QuestionBankImportResult(
            bank_version_id=bank_version_id,
            question_count=len(existing_manifest),
            manifest_count=len(existing_manifest),
            n_core=version.n_core,
            n_tail=version.n_tail,
            weight_sum=sum((Decimal(row.weight_at_scan) for row in existing_manifest), Decimal("0")),
        )

    n_total = len(rows)
    n_core = initial_core_count(n_total)
    n_tail = n_total - n_core
    bank_version_id = str(uuid.uuid4())
    db.add(
        QuestionBankVersion(
            bank_version_id=bank_version_id,
            client_id=client_id,
            avs_version=QUESTION_BANK_AVS_VERSION,
            effective_from=selected_at,
            n_core=n_core,
            n_tail=n_tail,
            n_total=n_total,
            rotation_reason="phase12_initial_import",
        )
    )

    core_question_ids = _core_question_ids(rows, n_core=n_core)
    strategic_question_ids = strategic_question_ids or set()
    critical_question_ids = critical_question_ids or set()
    try:
        weight_inputs = [
            _question_weight_input(
                client_id,
                candidate,
                vertical=vertical,
                strategic_question_ids=strategic_question_ids,
                critical_question_ids=critical_question_ids,
            )
            for candidate, _ in rows
        ]
        weights = normalized_question_weights(weight_inputs, target_total=n_total)
    except ValueError as exc:
        raise QuestionBankImportError(str(exc)) from exc

    for (candidate, score), weight in zip(rows, weights, strict=True):
        question_id = _canonical_question_id(client_id, candidate)
        question = _get_or_create_question(db, client_id=client_id, question_id=question_id, candidate=candidate)
        _ensure_question_score(db, question_id=question.question_id, candidate=candidate, score=score)
        state = "FROZEN" if question.question_id in core_question_ids else "TAIL"
        db.add(
            QuestionBankMembership(
                bank_version_id=bank_version_id,
                question_id=question.question_id,
                state=state,
                weight=weight,
                entered_at=selected_at,
            )
        )
        db.add(
            ScanManifest(
                scan_id=scan_id,
                question_id=question.question_id,
                bank_version_id=bank_version_id,
                weight_at_scan=weight,
                state_at_scan=state,
            )
        )

    db.flush()
    return QuestionBankImportResult(
        bank_version_id=bank_version_id,
        question_count=n_total,
        manifest_count=n_total,
        n_core=n_core,
        n_tail=n_tail,
        weight_sum=sum(weights, Decimal("0")),
    )


def _core_question_ids(rows: list[tuple[QuestionCandidate, QuestionScore]], *, n_core: int) -> set[str]:
    ranked = sorted(
        rows,
        key=lambda row: (Decimal(row[1].weighted_score), row[0].id),
        reverse=True,
    )
    return {
        _canonical_question_id(row[0].client_id, row[0])
        for row in ranked[:n_core]
    }


def _get_or_create_question(
    db: Session,
    *,
    client_id: str,
    question_id: str,
    candidate: QuestionCandidate,
) -> QuestionBankQuestion:
    text_hash = candidate.text_hash or question_text_hash(candidate.text)
    existing = (
        db.query(QuestionBankQuestion)
        .filter(
            QuestionBankQuestion.client_id == client_id,
            QuestionBankQuestion.text_hash == text_hash,
        )
        .first()
    )
    if existing:
        if existing.text != candidate.text:
            raise QuestionBankImportError("Existing question text hash maps to different text")
        return existing

    try:
        brand_frame = canonical_brand_frame(candidate.brand_frame)
    except ValueError as exc:
        raise QuestionBankImportError(str(exc)) from exc

    question = QuestionBankQuestion(
        question_id=question_id,
        client_id=client_id,
        text=candidate.text,
        text_hash=text_hash,
        journey_stage=candidate.journey_stage,
        brand_frame=brand_frame,
        locality=candidate.locality or "L0",
        persona_id=_persona_id(client_id, candidate.persona),
        source="generated",
        created_at=candidate.created_at,
    )
    db.add(question)
    return question


def _question_weight_input(
    client_id: str,
    candidate: QuestionCandidate,
    *,
    vertical: str | None,
    strategic_question_ids: set[str],
    critical_question_ids: set[str],
) -> QuestionWeightInput:
    question_id = _canonical_question_id(client_id, candidate)
    return QuestionWeightInput(
        question_id=question_id,
        journey_stage=candidate.journey_stage,
        brand_frame=canonical_brand_frame(candidate.brand_frame),
        locality=candidate.locality,
        vertical=vertical,
        answer_stability=candidate.realism_score,
        strategic=_is_marked(candidate, question_id, strategic_question_ids),
        critical=_is_marked(candidate, question_id, critical_question_ids),
    )


def _is_marked(candidate: QuestionCandidate, canonical_question_id: str, marked_ids: set[str]) -> bool:
    return candidate.id in marked_ids or canonical_question_id in marked_ids


def _ensure_question_score(
    db: Session,
    *,
    question_id: str,
    candidate: QuestionCandidate,
    score: QuestionScore,
) -> None:
    existing = (
        db.query(QuestionBankScore)
        .filter(
            QuestionBankScore.question_id == question_id,
            QuestionBankScore.scored_at == score.scored_at,
        )
        .first()
    )
    if existing:
        return

    db.add(
        QuestionBankScore(
            question_id=question_id,
            scored_at=score.scored_at,
            commercial_prox=score.d2_commercial_proximity,
            buyer_plausibility=score.d1_buyer_plausibility,
            construct_coverage=score.d3_cognitive_answerability,
            provider_diff=score.d4_diagnostic_power,
            goodhart_resistance=score.d5_statistical_identifiability,
            answer_stability=candidate.realism_score,
            composite=score.weighted_score,
            scorer_version=score.scorer_version,
        )
    )


def _canonical_question_id(client_id: str, candidate: QuestionCandidate) -> str:
    text_hash = candidate.text_hash or question_text_hash(candidate.text)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aiso-question:{client_id}:{text_hash}"))


def _persona_id(client_id: str, persona: str | None) -> str | None:
    cleaned = " ".join(str(persona or "").split()).lower()
    if not cleaned:
        return None
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aiso-persona:{client_id}:{cleaned}"))
