"""SQLAlchemy adapter for N-sampling plan preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import os
from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from api.adapters.audit_log import write_audit_event
from api.adapters.execution_state import record_step_once, safe_error, scan_step
from api.database import (
    ExecutionSample,
    MethodologyVersionSet,
    QuestionBankVersion,
    ScanManifest,
    ScanProgress,
    ScanRun,
)
from api.domain.sampling import (
    SAMPLES_PER_CELL,
    SAMPLING_CONFIG_VERSION,
    SamplePlanEntry,
    build_sample_plan,
)


PLANNED_PROVIDER_MODELS = {
    "openai": "gpt-4o-2024-08-06",
    "claude": "claude-sonnet-4-20250514",
    "perplexity": "sonar-pro",
    "gemini": "gemini-2.5-pro",
}


class SamplingPlanError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class SamplingPlanResult:
    scan_run_id: str
    question_count: int
    provider_count: int
    samples_per_cell: int
    planned_sample_count: int
    inserted_sample_count: int
    existing_sample_count: int
    stage: str


def prepare_sample_plan(db: Session, *, scan_run_id: str, actor_id: str) -> SamplingPlanResult:
    run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).first()
    if not run:
        raise SamplingPlanError("Scan run not found", status_code=404)

    progress = db.query(ScanProgress).filter(ScanProgress.scan_run_id == scan_run_id).first()
    if not progress:
        raise SamplingPlanError("Scan progress not found", status_code=409)

    providers = _providers_from_run(run)
    question_ids = _question_ids(db, scan_run_id=run.id, client_id=run.client_id)
    if not question_ids:
        raise SamplingPlanError("scan_manifest is required before preparing sample plan", status_code=409)

    existing_count = _sample_count(db, scan_run_id=run.id)
    planned_count = len(question_ids) * len(providers) * SAMPLES_PER_CELL
    _validate_progress_total(progress, planned_count=planned_count)
    if scan_step(db, scan_run_id=run.id, step_id="prepare_question_plan", event="succeeded"):
        return SamplingPlanResult(
            scan_run_id=run.id,
            question_count=len(question_ids),
            provider_count=len(providers),
            samples_per_cell=SAMPLES_PER_CELL,
            planned_sample_count=planned_count,
            inserted_sample_count=0,
            existing_sample_count=existing_count,
            stage=progress.stage,
        )

    entries = build_sample_plan(
        scan_id=run.id,
        question_ids=question_ids,
        providers=providers,
        provider_models=_planned_provider_models(providers),
        provider_model_snapshot_version=_provider_model_snapshot_version(db, run),
        issued_at=run.enqueued_at or _utcnow(),
        methodology_version=run.methodology_version,
    )
    try:
        inserted_count = _insert_sample_plan(db, entries)
    except Exception as exc:
        _record_prepare_failure(db, run=run, actor_id=actor_id, exc=exc)
        raise SamplingPlanError(f"Sample plan preparation failed: {exc}") from exc

    existing_after = _sample_count(db, scan_run_id=run.id)
    progress.stage = "sample_plan_prepared"
    progress.per_provider = _prepared_per_provider(
        progress.per_provider or {},
        providers=providers,
        per_provider_samples=len(question_ids) * SAMPLES_PER_CELL,
    )
    progress.updated_at = _utcnow()

    recorded = record_step_once(
        db,
        scan_run_id=run.id,
        step_id="prepare_question_plan",
        event="succeeded",
        payload={
            "question_count": len(question_ids),
            "provider_count": len(providers),
            "samples_per_cell": SAMPLES_PER_CELL,
            "planned_sample_count": planned_count,
            "inserted_sample_count": inserted_count,
            "sampling_config_version": SAMPLING_CONFIG_VERSION,
        },
    )
    if recorded:
        _write_sampling_audit(
            db,
            actor_id=actor_id,
            action="scan_run.sample_plan_prepared",
            resource_id=run.id,
            after_state={
                "scan_run_id": run.id,
                "stage": progress.stage,
                "planned_sample_count": planned_count,
                "inserted_sample_count": inserted_count,
                "sampling_config_version": SAMPLING_CONFIG_VERSION,
            },
            reason="Prepared deterministic N=5 sample plan from scan_manifest",
            correlation_id=run.idempotency_key,
        )
    db.flush()
    return SamplingPlanResult(
        scan_run_id=run.id,
        question_count=len(question_ids),
        provider_count=len(providers),
        samples_per_cell=SAMPLES_PER_CELL,
        planned_sample_count=planned_count,
        inserted_sample_count=inserted_count,
        existing_sample_count=existing_after,
        stage=progress.stage,
    )


def _insert_sample_plan(db: Session, entries: list[SamplePlanEntry]) -> int:
    if not entries:
        return 0
    values = [
        {
            "scan_run_id": entry.scan_id,
            "question_id": entry.question_id,
            "provider": entry.provider,
            "sample_index": entry.sample_index,
            "planned_provider_model": entry.planned_provider_model,
            "provider_model": None,
            "temperature": entry.temperature,
            "top_p": entry.top_p,
            "seed": entry.seed,
            "sample_plan_hash": entry.sample_plan_hash,
            "provider_idem_key": entry.provider_idempotency_key,
            "methodology_version": entry.methodology_version,
            "cache_bust": entry.cache_bust,
            "cost_usd": Decimal("0"),
        }
        for entry in entries
    ]
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    if dialect_name == "postgresql":
        statement = postgres_insert(ExecutionSample).values(values).on_conflict_do_nothing(
            index_elements=["scan_run_id", "question_id", "provider", "sample_index"]
        )
        result = db.execute(statement)
        return int(result.rowcount or 0)
    if dialect_name == "sqlite":
        statement = sqlite_insert(ExecutionSample).values(values).on_conflict_do_nothing(
            index_elements=["scan_run_id", "question_id", "provider", "sample_index"]
        )
        result = db.execute(statement)
        return int(result.rowcount or 0)

    inserted = 0
    for value in values:
        exists = (
            db.query(ExecutionSample)
            .filter(
                ExecutionSample.scan_run_id == value["scan_run_id"],
                ExecutionSample.question_id == value["question_id"],
                ExecutionSample.provider == value["provider"],
                ExecutionSample.sample_index == value["sample_index"],
            )
            .first()
        )
        if exists:
            continue
        db.add(ExecutionSample(**value))
        inserted += 1
    db.flush()
    return inserted


def _providers_from_run(run: ScanRun) -> list[str]:
    providers = [str(provider).strip().lower() for provider in (run.providers or []) if str(provider).strip()]
    if not providers:
        raise SamplingPlanError("Scan run must include an immutable provider list", status_code=409)
    return providers


def _question_ids(db: Session, *, scan_run_id: str, client_id: str) -> list[str]:
    rows = (
        db.query(ScanManifest)
        .join(QuestionBankVersion, QuestionBankVersion.bank_version_id == ScanManifest.bank_version_id)
        .filter(ScanManifest.scan_id == scan_run_id, QuestionBankVersion.client_id == client_id)
        .order_by(ScanManifest.question_id.asc())
        .all()
    )
    return [row.question_id for row in rows]


def _planned_provider_models(providers: list[str]) -> dict[str, str]:
    return {
        provider: os.getenv(f"AISO_SCAN_MODEL_{provider.upper()}", PLANNED_PROVIDER_MODELS[provider])
        for provider in providers
    }


def _provider_model_snapshot_version(db: Session, run: ScanRun) -> str:
    if not run.methodology_version_set_id:
        return "unknown"
    version_set = (
        db.query(MethodologyVersionSet)
        .filter(MethodologyVersionSet.id == run.methodology_version_set_id)
        .first()
    )
    if not version_set:
        raise SamplingPlanError("Methodology version set not found for scan run", status_code=409)
    return version_set.provider_model_snapshot_version


def _prepared_per_provider(
    per_provider: dict[str, Any],
    *,
    providers: list[str],
    per_provider_samples: int,
) -> dict[str, Any]:
    updated: dict[str, Any] = {}
    for provider in providers:
        current = dict((per_provider or {}).get(provider) or {})
        current["last_status"] = "sample_plan_prepared"
        current["planned"] = per_provider_samples
        updated[provider] = current
    return updated


def _validate_progress_total(progress: ScanProgress, *, planned_count: int) -> None:
    if progress.total_calls != planned_count:
        raise SamplingPlanError(
            "Scan progress total_calls does not match immutable scan-run plan",
            status_code=409,
        )


def _sample_count(db: Session, *, scan_run_id: str) -> int:
    return db.query(ExecutionSample).filter(ExecutionSample.scan_run_id == scan_run_id).count()


def _record_prepare_failure(db: Session, *, run: ScanRun, actor_id: str, exc: Exception) -> None:
    reason = safe_error(exc)
    recorded = record_step_once(
        db,
        scan_run_id=run.id,
        step_id="prepare_question_plan",
        event="failed",
        payload={"reason": reason},
    )
    if not recorded:
        return
    _write_sampling_audit(
        db,
        actor_id=actor_id,
        action="scan_run.sample_plan_failed",
        resource_id=run.id,
        after_state={"scan_run_id": run.id, "reason": reason},
        reason="Failed to prepare deterministic sample plan",
        correlation_id=run.idempotency_key,
    )
    db.flush()


def _write_sampling_audit(
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


def _audit_hmac_key() -> bytes:
    value = os.getenv("AISO_AUDIT_HMAC_KEY")
    if value:
        return value.encode("utf-8")
    if os.getenv("ENV") == "production":
        raise SamplingPlanError("Audit HMAC key is not configured", status_code=500)
    return b"aiso-local-dev-audit-key"


def _audit_hmac_key_version() -> int:
    return int(os.getenv("AISO_AUDIT_HMAC_KEY_VERSION", "1"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
