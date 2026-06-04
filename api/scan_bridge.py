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

from sqlalchemy.orm import Session

from api.database import (
    QuestionBankMembership,
    QuestionBankQuestion,
    QuestionBankVersion,
    ScanManifest,
)
from api.domain.question_generation import question_text_hash
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


class ScanBridgeError(RuntimeError):
    """Raised when a Phase 13 manifest cannot be built from the request."""


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
    if template_groups:
        rows.extend(profile_to_question_rows(profile or {}, selected_groups=template_groups))
    for question in custom_questions or []:
        text = " ".join(str(question or "").split())
        if text:
            rows.append({"question": text, "group": MANUAL_GROUP})

    # Deduplicate by text within this scan (a question can recur across groups).
    seen_hashes: set[str] = set()
    deduped: list[tuple[str, str]] = []  # (text, group)
    for row in rows:
        text = " ".join(str(row.get("question") or "").split())
        if not text:
            continue
        text_hash = question_text_hash(text)
        if text_hash in seen_hashes:
            continue
        seen_hashes.add(text_hash)
        deduped.append((text, str(row.get("group") or "")))

    if not deduped:
        raise ScanBridgeError("No questions generated for the selected groups")

    selected_at = datetime.now(timezone.utc)
    n_total = len(deduped)
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
            rotation_reason="phase0_bridge_import",
        )
    )

    for text, group in deduped:
        journey_stage, brand_frame = GROUP_TO_JOURNEY.get(group, _DEFAULT_JOURNEY)
        text_hash = question_text_hash(text)
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
                text=text,
                text_hash=text_hash,
                journey_stage=journey_stage,
                brand_frame=brand_frame,
                locality="L0",
                persona_id=None,
                source="manual" if group == MANUAL_GROUP else "generated",
            )
            db.add(question)
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
