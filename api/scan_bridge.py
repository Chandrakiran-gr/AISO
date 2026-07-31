"""Phase 0 bridge: current onboarding scan request → Phase 13 question manifest.

The live onboarding UI selects provider *groups* (G1–G7) and optional custom
questions; it does not yet run the full Phase 12 generate→score→select
pipeline that produces a curated question bank. This bridge synthesizes the
minimal question-bank artifacts (``QuestionBankVersion`` +
``QuestionBankQuestion`` + ``QuestionBankMembership`` + ``ScanManifest``) that
the Phase 13 kickoff (`create_or_replay_scan_run`) reads, mapping each legacy
group to a journey stage + brand frame so per-intent AVS analytics stay
meaningful.

This is an interim seam. When the full Phase 12 question intelligence is wired
into the UI, scans will be kicked off from a real selected portfolio and this
module is retired.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.orm import Session

from api.database import (
    QuestionBankMembership,
    QuestionBankQuestion,
    QuestionBankVersion,
    ScanManifest,
)
from api.domain.question_generation import JOURNEY_STAGES, question_text_hash
from api.question_generation import profile_to_question_rows
from api.question_gen.question_bank import QUESTION_BANK_AVS_VERSION
from api.scan_workspace import MANUAL_GROUP

# Authoritative G→(journey_stage, brand_frame) mapping, per
# methodology/question-bank-1.0.md §"Backward compatibility with G1–G7".
GROUP_TO_JOURNEY: dict[str, tuple[str, str]] = {
    "G1": ("J1", "U"),  # category & local discovery (unbranded)
    "G2": ("J2", "B"),  # direct brand (client named)
    "G3": ("J3", "C"),  # competitors & alternatives
    "G4": ("J4", "U"),  # transactional & bottom-funnel
    "G5": ("J5", "B"),  # trust, reviews & risk
    "G6": ("J6", "U"),  # fit: persona, occasion, constraint
    "G7": ("J4", "C"),  # head-to-head choice
    MANUAL_GROUP: ("J2", "U"),  # custom questions → neutral category exploration
}
_DEFAULT_JOURNEY = ("J2", "U")
_VALID_STAGES = set(JOURNEY_STAGES)

# The review-prompt generator tags each prompt with a full brand frame; the
# canonical question bank stores the collapsed 'U'|'B'|'C' axis (CHECK
# constraint). "Brand mentioned" -> B, "competitor only" -> C, else U.
_FRAME_TO_CANONICAL: dict[str, str] = {
    "unbranded_category": "U",
    "brand_only": "B",
    "branded_comparison": "B",
    "competitor_only": "C",
}


class _ManifestRow(NamedTuple):
    text: str
    journey_stage: str
    brand_frame: str  # canonical 'U' | 'B' | 'C'
    source: str  # "generated" | "manual"


class ScanBridgeError(RuntimeError):
    """Raised when a Phase 13 manifest cannot be built from the request."""


_PROFILE_SIGNAL_FIELDS = (
    "brand_name", "name", "category", "offerings", "services", "products",
    "product_categories", "service_offerings", "industry", "description",
)


def _profile_has_signal(profile: dict | None) -> bool:
    """True if the profile carries enough to generate meaningful questions."""
    if not profile:
        return False
    return any(str(profile.get(field) or "").strip() for field in _PROFILE_SIGNAL_FIELDS)


def _canonical_question_id(client_id: str, text_hash: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aiso-question:{client_id}:{text_hash}"))


def build_phase13_manifest_from_groups(
    db: Session,
    *,
    client_id: str,
    scan_id: str,
    groups: list[str],
    profile: dict | None,
    custom_questions: list[str] | None = None,
) -> int:
    """Create question-bank + manifest rows for ``scan_id`` from selected groups.

    Returns the number of manifest entries written. Idempotent at the question
    level via the (client_id, text_hash) unique constraint; raises if a manifest
    already exists for ``scan_id`` (kickoff replay is handled upstream).
    """
    if db.query(ScanManifest).filter(ScanManifest.scan_id == scan_id).first():
        raise ScanBridgeError(f"Scan manifest already exists for scan {scan_id}")

    rows: list[dict] = []
    template_groups = [g for g in groups if g != MANUAL_GROUP]
    has_custom = bool(custom_questions)
    if template_groups and not _profile_has_signal(profile) and not has_custom:
        # An empty/near-empty profile makes profile_to_question_rows emit generic
        # placeholder questions ("the business local business category"), which
        # would produce a meaningless scan. Refuse rather than scan on junk.
        raise ScanBridgeError(
            "Business profile is too sparse to generate questions. Complete the "
            "profile (brand, category/offerings) or provide custom questions."
        )
    if template_groups:
        rows.extend(profile_to_question_rows(profile or {}, selected_groups=template_groups))
    for question in custom_questions or []:
        text = " ".join(str(question or "").split())
        if text:
            rows.append({"question": text, "group": MANUAL_GROUP})

    # Deduplicate by text within this scan (a question can recur across groups),
    # mapping each group to its (journey_stage, brand_frame) and source.
    seen_hashes: set[str] = set()
    manifest_rows: list[_ManifestRow] = []
    for row in rows:
        text = " ".join(str(row.get("question") or "").split())
        if not text:
            continue
        text_hash = question_text_hash(text)
        if text_hash in seen_hashes:
            continue
        seen_hashes.add(text_hash)
        group = str(row.get("group") or "")
        journey_stage, brand_frame = GROUP_TO_JOURNEY.get(group, _DEFAULT_JOURNEY)
        manifest_rows.append(
            _ManifestRow(
                text=text,
                journey_stage=journey_stage,
                brand_frame=brand_frame,
                source="manual" if group == MANUAL_GROUP else "generated",
            )
        )

    if not manifest_rows:
        raise ScanBridgeError("No questions generated for the selected groups")

    return _write_question_bank_and_manifest(
        db,
        client_id=client_id,
        scan_id=scan_id,
        rows=manifest_rows,
        rotation_reason="phase0_bridge_import",
    )


def build_phase13_manifest_from_prompts(
    db: Session,
    *,
    client_id: str,
    scan_id: str,
    prompts: list[dict] | None,
) -> int:
    """Create question-bank + manifest rows from a user-approved prompt list.

    This is the seam the redesigned onboarding uses: the user reviews the
    LLM-generated natural prompts (branded / category), edits them,
    and launches - we scan exactly what they approved. The G1-G7 slot-template
    generator (``profile_to_question_rows``) is bypassed entirely, so the
    regex-extracted "offerings"/"locations" that produced garbage never run.

    Each ``prompt`` is ``{text, journey_stage?, brand_frame?}``. A prompt the user
    typed by hand (no frame) falls back to neutral category exploration.
    """
    if db.query(ScanManifest).filter(ScanManifest.scan_id == scan_id).first():
        raise ScanBridgeError(f"Scan manifest already exists for scan {scan_id}")

    seen_hashes: set[str] = set()
    manifest_rows: list[_ManifestRow] = []
    for prompt in prompts or []:
        entry = prompt if isinstance(prompt, dict) else {}
        text = " ".join(str(entry.get("text") or "").split())
        if not text:
            continue
        text_hash = question_text_hash(text)
        if text_hash in seen_hashes:
            continue
        seen_hashes.add(text_hash)
        stage = str(entry.get("journey_stage") or "").strip().upper()
        if stage not in _VALID_STAGES:
            stage = _DEFAULT_JOURNEY[0]
        frame = _FRAME_TO_CANONICAL.get(
            str(entry.get("brand_frame") or "").strip().lower(), _DEFAULT_JOURNEY[1]
        )
        manifest_rows.append(
            _ManifestRow(text=text, journey_stage=stage, brand_frame=frame, source="generated")
        )

    if not manifest_rows:
        raise ScanBridgeError("No prompts provided for the scan")

    return _write_question_bank_and_manifest(
        db,
        client_id=client_id,
        scan_id=scan_id,
        rows=manifest_rows,
        rotation_reason="onboarding_review_import",
    )


def _write_question_bank_and_manifest(
    db: Session,
    *,
    client_id: str,
    scan_id: str,
    rows: list[_ManifestRow],
    rotation_reason: str,
) -> int:
    """Persist a question-bank version + questions + memberships + manifest.

    These four models carry only bare ``ForeignKey`` columns and no ORM
    ``relationship()``s, so SQLAlchemy's unit of work does NOT order the parent
    (``question_bank_version`` / ``question``) INSERTs before the child
    (``question_bank_membership`` / ``scan_manifest``) rows that reference them
    within a single flush. The FK constraints are enforced at statement time, so
    we persist each parent layer before adding its children - flush the version,
    then all questions, then the memberships + manifest. All of this stays inside
    the caller's transaction, so a later failure still rolls back the whole
    manifest.
    """
    selected_at = datetime.now(timezone.utc)
    n_total = len(rows)
    bank_version_id = str(uuid.uuid4())

    db.add(
        QuestionBankVersion(
            bank_version_id=bank_version_id,
            client_id=client_id,
            avs_version=QUESTION_BANK_AVS_VERSION,
            effective_from=selected_at,
            n_core=n_total,  # bridge: treat all as frozen core
            n_tail=0,
            n_total=n_total,
            rotation_reason=rotation_reason,
        )
    )
    db.flush()  # version must exist before any membership/manifest references it

    questions: list[QuestionBankQuestion] = []
    for row in rows:
        text_hash = question_text_hash(row.text)
        question_id = _canonical_question_id(client_id, text_hash)
        question = (
            db.query(QuestionBankQuestion)
            .filter(
                QuestionBankQuestion.client_id == client_id,
                QuestionBankQuestion.text_hash == text_hash,
            )
            .first()
        )
        if question is None:
            question = QuestionBankQuestion(
                question_id=question_id,
                client_id=client_id,
                text=row.text,
                text_hash=text_hash,
                journey_stage=row.journey_stage,
                brand_frame=row.brand_frame,
                locality="L0",
                persona_id=None,
                source=row.source,
            )
            db.add(question)
        questions.append(question)
    db.flush()  # every question must exist before its membership/manifest rows

    for question in questions:
        db.add(
            QuestionBankMembership(
                bank_version_id=bank_version_id,
                question_id=question.question_id,
                state="FROZEN",
                weight=Decimal("1.0"),
                entered_at=selected_at,
            )
        )
        db.add(
            ScanManifest(
                scan_id=scan_id,
                question_id=question.question_id,
                bank_version_id=bank_version_id,
                weight_at_scan=Decimal("1.0"),
                state_at_scan="FROZEN",
            )
        )

    db.flush()
    return n_total
