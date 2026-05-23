"""Phase 12 selected-question CSV export and scan enqueue service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import csv
import json
import uuid

from sqlalchemy.orm import Session

from api import storage
from api.database import BusinessProfile, Client, QuestionCandidate, QuestionScore, Scan, ScanArtifact
from api.domain.ports import ScanEnqueueResult, ScanExecutor
from api.domain.question_selection import DEFAULT_SELECTION_TARGET_N


QUESTION_CSV_COLUMNS = [
    "scan_id",
    "client_id",
    "vertical",
    "objective",
    "selected_at",
    "question_id",
    "question_text",
    "journey_stage",
    "brand_frame",
    "intent_class",
    "persona",
    "weighted_score",
    "realism_score",
    "methodology_version",
]
QUESTION_CSV_METHODOLOGY_VERSION = "pipeline-1.0"


class QuestionExportError(ValueError):
    """Raised when selected questions cannot be exported for scan enqueue."""


@dataclass(frozen=True)
class QuestionPortfolioExport:
    scan_id: str
    scan_status: str
    selected_count: int
    selected_at: datetime
    artifact_id: str
    artifact_storage_backend: str
    artifact_storage_path: str
    artifact_original_filename: str
    enqueue_result: ScanEnqueueResult


def export_questions_and_enqueue_scan(
    db: Session,
    *,
    client_id: str,
    executor: ScanExecutor,
    target_n: int = DEFAULT_SELECTION_TARGET_N,
    scan_run_id: str | None = None,
) -> QuestionPortfolioExport:
    client, profile = _client_and_profile(db, client_id)
    rows = selected_question_rows(db, client_id)
    if len(rows) != target_n:
        raise QuestionExportError(f"Question CSV export requires {target_n} selected questions, found {len(rows)}")

    scan = _scan_for_export(db, client_id=client_id, scan_run_id=scan_run_id)
    selected_at = datetime.now(timezone.utc)
    filename = f"questions_{scan.id}.csv"
    local_path = storage.build_scan_artifact_path(client_id, scan.id, filename, stage="questions")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    _write_questions_csv(
        local_path,
        scan_id=scan.id,
        client_id=client_id,
        profile=profile,
        selected_at=selected_at,
        rows=rows,
    )

    metadata = storage.describe_configured_artifact(
        local_path,
        artifact_type="selected_questions_csv",
        client_name=client.name,
        client_id=client_id,
        scan_id=scan.id,
        original_filename=filename,
        metadata={
            "methodology_version": QUESTION_CSV_METHODOLOGY_VERSION,
            "selected_count": len(rows),
            "selected_at": selected_at.isoformat(),
        },
    )
    if storage.configured_storage_backend() == "onedrive" and metadata["storage_backend"] != "onedrive":
        upload_metadata = json.loads(metadata.get("metadata_json") or "{}")
        upload_error = upload_metadata.get("upload_error") or "OneDrive upload did not complete"
        raise QuestionExportError(f"Question CSV export to OneDrive failed: {upload_error}")

    artifact = ScanArtifact(
        id=str(uuid.uuid4()),
        client_id=client_id,
        scan_id=scan.id,
        **metadata,
    )
    db.add(artifact)

    scan.status = "ready"
    scan.groups = json.dumps(["phase12_selected_questions"])
    scan.providers = scan.providers or json.dumps([])
    enqueue_result = executor.enqueue(scan_id=scan.id, client_id=client_id)
    db.flush()

    return QuestionPortfolioExport(
        scan_id=scan.id,
        scan_status=scan.status,
        selected_count=len(rows),
        selected_at=selected_at,
        artifact_id=artifact.id,
        artifact_storage_backend=artifact.storage_backend,
        artifact_storage_path=artifact.storage_path,
        artifact_original_filename=artifact.original_filename or filename,
        enqueue_result=enqueue_result,
    )


def selected_question_rows(db: Session, client_id: str) -> list[tuple[QuestionCandidate, QuestionScore]]:
    candidates = (
        db.query(QuestionCandidate)
        .filter(
            QuestionCandidate.client_id == client_id,
            QuestionCandidate.selected.is_(True),
        )
        .order_by(QuestionCandidate.journey_stage.asc(), QuestionCandidate.brand_frame.asc(), QuestionCandidate.id.asc())
        .all()
    )
    candidate_ids = [candidate.id for candidate in candidates]
    if not candidate_ids:
        return []
    scores_by_question: dict[str, QuestionScore] = {}
    scores = (
        db.query(QuestionScore)
        .filter(QuestionScore.question_id.in_(candidate_ids))
        .order_by(QuestionScore.question_id.asc(), QuestionScore.scored_at.desc())
        .all()
    )
    for score in scores:
        if score.question_id not in scores_by_question:
            scores_by_question[score.question_id] = score
    return [
        (candidate, scores_by_question[candidate.id])
        for candidate in candidates
        if candidate.id in scores_by_question
    ]


def _write_questions_csv(
    path,
    *,
    scan_id: str,
    client_id: str,
    profile: BusinessProfile,
    selected_at: datetime,
    rows: list[tuple[QuestionCandidate, QuestionScore]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUESTION_CSV_COLUMNS)
        writer.writeheader()
        for candidate, score in rows:
            writer.writerow(
                {
                    "scan_id": scan_id,
                    "client_id": client_id,
                    "vertical": profile.vertical,
                    "objective": profile.objective,
                    "selected_at": selected_at.isoformat(),
                    "question_id": candidate.id,
                    "question_text": candidate.text,
                    "journey_stage": candidate.journey_stage,
                    "brand_frame": candidate.brand_frame,
                    "intent_class": candidate.intent_class,
                    "persona": candidate.persona or "",
                    "weighted_score": _decimal_text(score.weighted_score),
                    "realism_score": _decimal_text(candidate.realism_score),
                    "methodology_version": QUESTION_CSV_METHODOLOGY_VERSION,
                }
            )


def _client_and_profile(db: Session, client_id: str) -> tuple[Client, BusinessProfile]:
    client = db.query(Client).filter(Client.id == client_id).first()
    profile = db.query(BusinessProfile).filter(BusinessProfile.client_id == client_id).first()
    if not client or not profile:
        raise QuestionExportError("Onboarding profile not found")
    return client, profile


def _scan_for_export(db: Session, *, client_id: str, scan_run_id: str | None) -> Scan:
    if scan_run_id:
        scan = db.query(Scan).filter(Scan.id == scan_run_id, Scan.client_id == client_id).first()
        if not scan:
            raise QuestionExportError("Scan run not found")
        return scan
    scan = Scan(
        id=str(uuid.uuid4()),
        client_id=client_id,
        status="ready",
        providers=json.dumps([]),
        groups=json.dumps(["phase12_selected_questions"]),
    )
    db.add(scan)
    db.flush()
    return scan


def _decimal_text(value) -> str:
    if value is None:
        return ""
    return f"{Decimal(value):.3f}"
