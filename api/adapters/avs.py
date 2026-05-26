"""SQLAlchemy adapter for AVS-1.0 computation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import socket
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from api.adapters.audit_log import write_audit_event
from api.adapters.execution_state import record_step_once, scan_step
from api.database import (
    AVSComputation,
    Classification,
    Client,
    Sample,
    ScanManifest,
    ScanProgress,
    ScanProvenance,
    ScanRawResponseArchive,
    ScanResult,
    ScanRun,
)
from api.domain.avs import (
    BOOTSTRAP_PRODUCTION_ITERATIONS,
    AVSSample,
    compute_avs,
)
from api.domain.classifier import CLASSIFIER_VERSION


RAW_RESPONSE_ARCHIVE_TYPE = "provider_raw_responses"


class AVSComputationError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AVSComputationResult:
    scan_run_id: str
    avs_value: float
    presence: float
    prominence: float
    positivity: float
    ci_lower_95: float
    ci_upper_95: float
    ci_method: str
    bootstrap_iterations: int
    completeness: str
    already_recorded: bool = False


def compute_scan_avs(
    db: Session,
    *,
    scan_run_id: str,
    actor_id: str,
    bootstrap_iterations: int | None = None,
    bootstrap_seed: int = 42,
) -> AVSComputationResult:
    run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).first()
    if not run:
        raise AVSComputationError("Scan run not found", status_code=404)
    if not run.methodology_version_set_id:
        raise AVSComputationError("Scan run is missing methodology_version_set_id", status_code=409)
    progress = db.query(ScanProgress).filter(ScanProgress.scan_run_id == scan_run_id).first()
    if not progress:
        raise AVSComputationError("Scan progress not found", status_code=409)

    existing = (
        db.query(AVSComputation)
        .filter(
            AVSComputation.scan_id == scan_run_id,
            AVSComputation.methodology_version_set_id == run.methodology_version_set_id,
        )
        .first()
    )
    if existing and scan_step(db, scan_run_id=run.id, step_id="compute_avs", event="succeeded"):
        return AVSComputationResult(
            scan_run_id=run.id,
            avs_value=float(existing.avs_value),
            presence=float(existing.presence),
            prominence=float(existing.prominence),
            positivity=float(existing.positivity),
            ci_lower_95=float(existing.ci_lower_95),
            ci_upper_95=float(existing.ci_upper_95),
            ci_method=existing.ci_method,
            bootstrap_iterations=int(existing.bootstrap_iterations or 0),
            completeness=run.completeness or "complete",
            already_recorded=True,
        )

    try:
        if existing:
            raise AVSComputationError(
                "AVS computation already exists without a succeeded idempotency step; manual repair required",
                status_code=409,
            )

        client = db.query(Client).filter(Client.id == run.client_id).one()
        samples_by_pair = _avs_samples_by_pair(db, run=run)
        if not samples_by_pair:
            raise AVSComputationError("No classified samples are available for AVS computation", status_code=409)
        completeness = _completion_class(db, run=run)
        if completeness == "failed":
            raise AVSComputationError("Insufficient successful samples for AVS computation", status_code=409)

        iterations = bootstrap_iterations or _bootstrap_iterations()
        result = compute_avs(
            samples_by_pair,
            target_aliases=_target_aliases(client),
            bootstrap_iterations=iterations,
            bootstrap_seed=bootstrap_seed,
        )

        provenance = _ensure_scan_provenance(db, run=run)
        computation = AVSComputation(
            id=str(uuid.uuid4()),
            scan_id=run.id,
            methodology_version_set_id=run.methodology_version_set_id,
            is_primary=True,
        )
        db.add(computation)
        computation.avs_value = _decimal3(result.avs_value)
        computation.presence = _decimal5(result.presence)
        computation.prominence = _decimal5(result.prominence)
        computation.positivity = _decimal5(result.positivity)
        computation.ci_lower_95 = _decimal3(result.ci_lower_95)
        computation.ci_upper_95 = _decimal3(result.ci_upper_95)
        computation.ci_method = result.ci_method
        computation.bootstrap_iterations = result.bootstrap_iterations
        computation.computed_at = _utcnow()
        computation.computed_by_git_sha = _git_sha()

        _update_scan_state(run=run, progress=progress, completeness=completeness)
        _update_legacy_visibility_projection(db, scan_id=run.id, avs_value=result.avs_value)
        recorded = record_step_once(
            db,
            scan_run_id=run.id,
            step_id="compute_avs",
            event="succeeded",
            payload={
                "methodology_version_set_id": run.methodology_version_set_id,
                "scan_provenance_hash": provenance.this_provenance_hash.hex(),
                "avs_value": round(result.avs_value, 3),
                "presence": round(result.presence, 5),
                "prominence": round(result.prominence, 5),
                "positivity": round(result.positivity, 5),
                "ci_method": result.ci_method,
                "bootstrap_iterations": result.bootstrap_iterations,
                "completeness": completeness,
                "zero_mentions": result.zero_mentions,
            },
        )
        if recorded:
            _write_avs_audit(
                db,
                actor_id=actor_id,
                action="scan_run.avs_computed",
                resource_id=run.id,
                after_state={
                    "scan_run_id": run.id,
                    "methodology_version_set_id": run.methodology_version_set_id,
                    "avs_value": round(result.avs_value, 3),
                    "status": run.status,
                    "completeness": completeness,
                    "stage": progress.stage,
                },
                reason="Computed AVS-1.0 projection from classified samples",
                correlation_id=run.idempotency_key,
            )
    except AVSComputationError as exc:
        _mark_avs_failed(db, run=run, progress=progress, reason=str(exc))
        raise

    db.flush()
    return AVSComputationResult(
        scan_run_id=run.id,
        avs_value=float(computation.avs_value),
        presence=float(computation.presence),
        prominence=float(computation.prominence),
        positivity=float(computation.positivity),
        ci_lower_95=float(computation.ci_lower_95),
        ci_upper_95=float(computation.ci_upper_95),
        ci_method=computation.ci_method,
        bootstrap_iterations=int(computation.bootstrap_iterations or 0),
        completeness=completeness,
        already_recorded=False,
    )


def _avs_samples_by_pair(db: Session, *, run: ScanRun) -> dict[tuple[str, str], list[AVSSample]]:
    weights = _manifest_weights(db, scan_id=run.id)
    samples = db.query(Sample).filter(Sample.scan_id == run.id).all()
    if not samples:
        return {}

    stance_rows = (
        db.query(Classification)
        .filter(
            Classification.sample_id.in_([sample.id for sample in samples]),
            Classification.classifier_type == "stance",
            Classification.classifier_version == CLASSIFIER_VERSION,
        )
        .all()
    )
    stance_by_sample = {row.sample_id: row for row in stance_rows}
    missing_stance = sorted(sample.id for sample in samples if sample.id not in stance_by_sample)
    if missing_stance:
        preview = ", ".join(missing_stance[:5])
        suffix = "" if len(missing_stance) <= 5 else f", +{len(missing_stance) - 5} more"
        raise AVSComputationError(
            f"Missing {CLASSIFIER_VERSION} stance classification for AVS samples: {preview}{suffix}",
            status_code=409,
        )

    grouped: dict[tuple[str, str], list[AVSSample]] = {}
    for sample in samples:
        stance = stance_by_sample.get(sample.id)
        if not stance:
            continue
        grouped.setdefault((sample.question_id, sample.provider), []).append(
            AVSSample(
                question_id=sample.question_id,
                provider=sample.provider,
                sample_index=sample.sample_index,
                text=_sample_text(sample),
                stance_label=stance.consensus_value,
                stance_confidence=float(stance.consensus_confidence or 0),
                question_weight=weights.get(sample.question_id, 1.0),
            )
        )
    return {
        pair: sorted(values, key=lambda item: item.sample_index)
        for pair, values in sorted(grouped.items())
    }


def _manifest_weights(db: Session, *, scan_id: str) -> dict[str, float]:
    rows = db.query(ScanManifest).filter(ScanManifest.scan_id == scan_id).all()
    if not rows:
        return {}
    raw = {row.question_id: max(float(row.weight_at_scan or 1), 0.0) for row in rows}
    total = sum(raw.values())
    if total <= 0:
        return {question_id: 1.0 for question_id in raw}
    scale = len(raw) / total
    return {question_id: value * scale for question_id, value in raw.items()}


def _completion_class(db: Session, *, run: ScanRun) -> str:
    from api.database import ExecutionSample

    planned = db.query(ExecutionSample).filter(ExecutionSample.scan_run_id == run.id).all()
    if not planned:
        return "failed"
    successful = [sample for sample in planned if sample.raw_response_hash is not None and sample.failure_reason is None]
    if not successful:
        return "failed"
    if len(successful) == len(planned):
        return "complete"

    providers = sorted({sample.provider for sample in planned})
    failed_provider_count = 0
    for provider in providers:
        provider_success = [sample for sample in successful if sample.provider == provider]
        if not provider_success:
            failed_provider_count += 1

    planned_cells = {(sample.question_id, sample.provider) for sample in planned}
    successful_cells: dict[tuple[str, str], int] = {}
    for sample in successful:
        cell = (sample.question_id, sample.provider)
        successful_cells[cell] = successful_cells.get(cell, 0) + 1
    if failed_provider_count > len(providers) / 2:
        return "failed"
    if planned_cells - set(successful_cells):
        return "partial_degraded"
    if successful_cells and min(successful_cells.values()) >= 3:
        return "partial_acceptable"
    return "partial_degraded"


def _ensure_scan_provenance(db: Session, *, run: ScanRun) -> ScanProvenance:
    existing = db.query(ScanProvenance).filter(ScanProvenance.scan_id == run.id).first()
    if existing:
        return existing
    raw_archive = (
        db.query(ScanRawResponseArchive)
        .filter(
            ScanRawResponseArchive.scan_id == run.id,
            ScanRawResponseArchive.archive_type == RAW_RESPONSE_ARCHIVE_TYPE,
        )
        .first()
    )
    if not raw_archive:
        raise AVSComputationError("Raw response archive must exist before AVS provenance is signed", status_code=409)

    archive_path = Path(raw_archive.archive_url)
    if not archive_path.is_absolute():
        from api import storage

        archive_path = storage.REPO_ROOT / archive_path
    archive_bytes = archive_path.read_bytes()
    archive_hash = hashlib.sha256(archive_bytes).digest()
    if archive_hash != raw_archive.archive_hash:
        raise AVSComputationError("Raw response archive hash mismatch", status_code=409)

    manifest_hash = _scan_manifest_hash(db, scan_id=run.id)
    previous = db.query(ScanProvenance).order_by(ScanProvenance.signed_at.desc()).first()
    prev_hash = previous.this_provenance_hash if previous else b"\x00" * 32
    now = _utcnow()
    payload = {
        "scan_id": run.id,
        "client_id": run.client_id,
        "methodology_version_set_id": run.methodology_version_set_id,
        "scan_started_at": _iso(run.started_at or run.enqueued_at or now),
        "scan_completed_at": _iso(now),
        "question_count": db.query(ScanManifest).filter(ScanManifest.scan_id == run.id).count(),
        "sample_count": raw_archive.sample_count,
        "raw_response_archive_hash": archive_hash.hex(),
        "scan_manifest_hash": manifest_hash.hex(),
        "git_sha": _git_sha(),
        "computed_by_host": socket.gethostname(),
        "prev_provenance_hash": prev_hash.hex(),
    }
    this_hash = hashlib.sha256(
        prev_hash + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).digest()
    row = ScanProvenance(
        scan_id=run.id,
        client_id=run.client_id,
        methodology_version_set_id=run.methodology_version_set_id,
        scan_started_at=run.started_at or run.enqueued_at or now,
        scan_completed_at=now,
        question_count=payload["question_count"],
        sample_count=raw_archive.sample_count,
        raw_response_archive_url=raw_archive.archive_url,
        raw_response_archive_hash=archive_hash,
        scan_manifest_hash=manifest_hash,
        git_sha=payload["git_sha"],
        computed_by_host=payload["computed_by_host"],
        prev_provenance_hash=prev_hash,
        this_provenance_hash=this_hash,
        signed_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _scan_manifest_hash(db: Session, *, scan_id: str) -> bytes:
    rows = (
        db.query(ScanManifest)
        .filter(ScanManifest.scan_id == scan_id)
        .order_by(ScanManifest.question_id.asc())
        .all()
    )
    payload = [
        {
            "question_id": row.question_id,
            "bank_version_id": row.bank_version_id,
            "weight_at_scan": str(row.weight_at_scan),
            "state_at_scan": row.state_at_scan,
        }
        for row in rows
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).digest()


def _update_scan_state(*, run: ScanRun, progress: ScanProgress, completeness: str) -> None:
    run.completeness = completeness
    run.status = "succeeded" if completeness in {"complete", "partial_acceptable"} else "partial"
    run.finished_at = run.finished_at or _utcnow()
    progress.status = run.status
    progress.stage = "avs_computed"
    progress.updated_at = _utcnow()


def _mark_avs_failed(db: Session, *, run: ScanRun, progress: ScanProgress, reason: str) -> None:
    run.status = "failed"
    run.completeness = "failed"
    run.error_summary = {"stage": "avs", "reason": reason}
    progress.status = "failed"
    progress.stage = "avs_failed"
    progress.updated_at = _utcnow()
    record_step_once(
        db,
        scan_run_id=run.id,
        step_id="compute_avs",
        event="failed",
        payload={"reason": reason},
    )


def _update_legacy_visibility_projection(db: Session, *, scan_id: str, avs_value: float) -> None:
    rows = db.query(ScanResult).filter(ScanResult.scan_id == scan_id).all()
    for row in rows:
        row.visibility_score = round(avs_value, 2)


def _target_aliases(client: Client) -> list[str]:
    aliases = [client.name]
    host = urlparse(client.url if "://" in client.url else f"https://{client.url}").hostname or ""
    if host.startswith("www."):
        host = host[4:]
    if host:
        aliases.append(host.split(".")[0])
        aliases.append(host)
    return [alias for alias in aliases if alias]


def _sample_text(sample: Sample) -> str:
    if sample.raw_response_text is not None:
        return sample.raw_response_text
    if sample.raw_response_pointer:
        path = Path(sample.raw_response_pointer)
        if not path.is_absolute():
            from api import storage

            path = storage.REPO_ROOT / path
        return path.read_text(encoding="utf-8")
    return ""


def _write_avs_audit(
    db: Session,
    *,
    actor_id: str,
    action: str,
    resource_id: str,
    after_state: dict[str, Any],
    reason: str,
    correlation_id: str,
) -> None:
    write_audit_event(
        db,
        actor_type="system" if actor_id == "system" else "user",
        actor_id=actor_id,
        action=action,
        resource_type="scan_run",
        resource_id=resource_id,
        after_state=after_state,
        reason=reason,
        correlation_id=correlation_id,
        hmac_key=_audit_hmac_key(),
        hmac_key_version=_audit_hmac_key_version(),
    )


def _bootstrap_iterations() -> int:
    return int(os.getenv("AISO_AVS_BOOTSTRAP_ITERATIONS", str(BOOTSTRAP_PRODUCTION_ITERATIONS)))


def _audit_hmac_key() -> bytes:
    value = os.getenv("AISO_AUDIT_HMAC_KEY")
    if value:
        return value.encode("utf-8")
    if os.getenv("ENV") == "production":
        raise AVSComputationError("Audit HMAC key is not configured", status_code=500)
    return b"aiso-local-dev-audit-key"


def _audit_hmac_key_version() -> int:
    return int(os.getenv("AISO_AUDIT_HMAC_KEY_VERSION", "1"))


def _git_sha() -> str:
    return os.getenv("AISO_GIT_SHA", "unknown")


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _decimal3(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"))


def _decimal5(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.00001"))
