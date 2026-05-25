"""SQLAlchemy adapter for downstream scan-run kickoff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import os
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.adapters.audit_log import write_audit_event
from api.database import (
    Client,
    IdempotencyKey,
    MethodologyVersionSet,
    QuestionBankVersion,
    ScanManifest,
    ScanProgress,
    ScanRun,
    ScanStep,
)
from api.domain.scan_runs import (
    ManifestEntry,
    build_scan_run_plan,
    normalize_latency_class,
    normalize_providers,
    request_hash,
    validate_idempotency_key,
    validate_scan_run_id,
)


class ScanRunKickoffError(ValueError):
    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ScanRunKickoffResult:
    status_code: int
    body: dict[str, Any]


def create_or_replay_scan_run(
    db: Session,
    *,
    client_id: str,
    user_id: str,
    source_scan_id: str,
    idempotency_key: str,
    providers: list[str] | None = None,
    cost_budget_usd: Decimal | None = None,
    latency_class: str | None = None,
    complete_idempotency_response: bool = True,
) -> ScanRunKickoffResult:
    idempotency_key = _validated_idempotency_key(idempotency_key)
    source_scan_id = _validated_scan_run_id(source_scan_id)
    client = db.query(Client).filter(Client.id == client_id, Client.user_id == user_id).first()
    if not client:
        raise ScanRunKickoffError("Client not found", status_code=404)

    version_set = _active_methodology_version_set(db)
    normalized_providers = _normalized_providers(providers)
    normalized_latency = _normalized_latency_class(latency_class)
    budget = _money4(Decimal(cost_budget_usd if cost_budget_usd is not None else client.cost_budget_default_usd))
    request_body = {
        "client_id": client_id,
        "source_scan_id": source_scan_id,
        "providers": list(normalized_providers),
        "cost_budget_usd": str(budget),
        "latency_class": normalized_latency,
    }
    fingerprint = request_hash(request_body)

    idempotency, created_idempotency = _get_or_create_idempotency(
        db,
        idempotency_key=idempotency_key,
        request_hash_value=fingerprint,
    )
    if not created_idempotency:
        if idempotency.completed_at and idempotency.response_body:
            body = dict(idempotency.response_body)
            _write_scan_run_audit(
                db,
                actor_id=user_id,
                action="scan_run.idempotency_replayed",
                resource_id=body.get("scan_run_id", source_scan_id),
                after_state=body,
                reason="HTTP idempotency replay",
                correlation_id=idempotency_key,
            )
            return ScanRunKickoffResult(
                status_code=idempotency.response_status or 200,
                body=body,
            )

        existing_inflight = (
            db.query(ScanRun)
            .filter(ScanRun.client_id == client_id, ScanRun.idempotency_key == idempotency_key)
            .first()
        )
        if not existing_inflight:
            raise ScanRunKickoffError("Idempotent scan-run request is already in progress", status_code=409)

    existing_run = db.query(ScanRun).filter(ScanRun.id == source_scan_id, ScanRun.client_id == client_id).first()
    if existing_run:
        if existing_run.idempotency_key != idempotency_key:
            raise ScanRunKickoffError("Source scan already has a downstream scan run", status_code=409)
        body = _response_body_for_run(
            db,
            existing_run,
            providers=normalized_providers,
            samples_per_cell=5,
            question_count=_manifest_count(db, source_scan_id, client_id=client_id),
            total_calls=_progress_total_calls(db, source_scan_id),
            manifest_hash=None,
        )
        if complete_idempotency_response:
            _complete_idempotency(idempotency, status_code=200, body=body)
        _write_scan_run_audit(
            db,
            actor_id=user_id,
            action="scan_run.idempotency_replayed",
            resource_id=existing_run.id,
            after_state=body,
            reason="Recovered incomplete idempotency response from existing scan run",
            correlation_id=idempotency_key,
        )
        db.flush()
        return ScanRunKickoffResult(status_code=200, body=body)

    manifest_entries = _manifest_entries(db, source_scan_id, client_id=client_id)
    try:
        plan = build_scan_run_plan(
            source_scan_id=source_scan_id,
            providers=normalized_providers,
            manifest_entries=manifest_entries,
            cost_budget_usd=budget,
            latency_class=normalized_latency,
        )
    except ValueError as exc:
        raise ScanRunKickoffError(str(exc), status_code=409) from exc

    run = ScanRun(
        id=source_scan_id,
        client_id=client_id,
        idempotency_key=idempotency_key,
        methodology_version=plan.methodology_version,
        methodology_version_set_id=version_set.id,
        status="queued",
        cost_budget_usd=plan.cost_budget_usd,
        cost_spent_usd=Decimal("0"),
        latency_class=plan.latency_class,
        providers=list(plan.providers),
        enqueued_at=_utcnow(),
    )
    db.add(run)
    db.add(
        ScanProgress(
            scan_run_id=run.id,
            status="queued",
            stage="queued",
            total_calls=plan.total_calls,
            completed_calls=0,
            failed_calls=0,
            per_provider={
                provider: {"completed": 0, "failed": 0, "rate_limited": 0, "last_status": "queued"}
                for provider in plan.providers
            },
        )
    )
    db.add(
        ScanStep(
            scan_run_id=run.id,
            step_id="create_scan_run",
            event="succeeded",
            attempt=1,
            payload={
                "question_count": plan.question_count,
                "total_calls": plan.total_calls,
                "providers": list(plan.providers),
                "scan_manifest_hash": plan.manifest_hash,
            },
        )
    )

    body = _response_body_for_run(
        db,
        run,
        providers=plan.providers,
        samples_per_cell=plan.samples_per_cell,
        question_count=plan.question_count,
        total_calls=plan.total_calls,
        manifest_hash=plan.manifest_hash,
    )
    if complete_idempotency_response:
        _complete_idempotency(idempotency, status_code=201, body=body)
    _write_scan_run_audit(
        db,
        actor_id=user_id,
        action="scan_run.created",
        resource_id=run.id,
        after_state={
            **body,
            "methodology_version_set_id": version_set.id,
        },
        reason="Created downstream scan run from selected-question scan_manifest",
        correlation_id=idempotency_key,
    )
    db.flush()
    return ScanRunKickoffResult(status_code=201, body=body)


def complete_scan_run_idempotency_response(
    db: Session,
    *,
    idempotency_key: str,
    status_code: int,
    body: dict[str, Any],
) -> None:
    idempotency = db.query(IdempotencyKey).filter(IdempotencyKey.key == idempotency_key).first()
    if not idempotency:
        raise ScanRunKickoffError("Idempotency key not found", status_code=409)
    _complete_idempotency(idempotency, status_code=status_code, body=body)
    db.flush()


def progress_for_scan_run(db: Session, *, scan_run_id: str, user_id: str) -> dict[str, Any] | None:
    run = (
        db.query(ScanRun)
        .join(Client, Client.id == ScanRun.client_id)
        .filter(ScanRun.id == scan_run_id, Client.user_id == user_id)
        .first()
    )
    if not run:
        return None
    progress = db.query(ScanProgress).filter(ScanProgress.scan_run_id == scan_run_id).first()
    if not progress:
        return None
    return {
        "scan_run_id": run.id,
        "client_id": run.client_id,
        "status": progress.status,
        "stage": progress.stage,
        "total_calls": progress.total_calls,
        "completed_calls": progress.completed_calls,
        "failed_calls": progress.failed_calls,
        "per_provider": progress.per_provider or {},
        "eta_seconds": progress.eta_seconds,
        "cost_spent_usd": str(run.cost_spent_usd),
        "cost_budget_usd": str(_money4(Decimal(run.cost_budget_usd))),
        "methodology_version": run.methodology_version,
        "methodology_version_set_id": run.methodology_version_set_id,
    }


def _validated_idempotency_key(value: str) -> str:
    try:
        return validate_idempotency_key(value)
    except ValueError as exc:
        raise ScanRunKickoffError(str(exc), status_code=400) from exc


def _validated_scan_run_id(value: str) -> str:
    try:
        return validate_scan_run_id(value)
    except ValueError as exc:
        raise ScanRunKickoffError(str(exc), status_code=400) from exc


def _get_or_create_idempotency(
    db: Session,
    *,
    idempotency_key: str,
    request_hash_value: str,
) -> tuple[IdempotencyKey, bool]:
    existing = db.query(IdempotencyKey).filter(IdempotencyKey.key == idempotency_key).first()
    if existing:
        _validate_existing_idempotency(existing, request_hash_value=request_hash_value)
        return existing, False

    idempotency = IdempotencyKey(
        key=idempotency_key,
        scope="scan_run.create",
        request_hash=request_hash_value,
        locked_at=_utcnow(),
    )
    db.add(idempotency)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        existing = db.query(IdempotencyKey).filter(IdempotencyKey.key == idempotency_key).first()
        if not existing:
            raise ScanRunKickoffError("Could not acquire idempotency key", status_code=409) from exc
        _validate_existing_idempotency(existing, request_hash_value=request_hash_value)
        return existing, False
    return idempotency, True


def _validate_existing_idempotency(
    idempotency: IdempotencyKey,
    *,
    request_hash_value: str,
) -> None:
    if idempotency.scope != "scan_run.create" or idempotency.request_hash != request_hash_value:
        raise ScanRunKickoffError("Idempotency-Key was already used for a different request", status_code=409)


def _normalized_providers(value: list[str] | None) -> tuple[str, ...]:
    try:
        return normalize_providers(value)
    except ValueError as exc:
        raise ScanRunKickoffError(str(exc), status_code=422) from exc


def _normalized_latency_class(value: str | None) -> str:
    try:
        return normalize_latency_class(value)
    except ValueError as exc:
        raise ScanRunKickoffError(str(exc), status_code=422) from exc


def _manifest_entries(db: Session, scan_id: str, *, client_id: str) -> list[ManifestEntry]:
    rows = (
        db.query(ScanManifest)
        .join(QuestionBankVersion, QuestionBankVersion.bank_version_id == ScanManifest.bank_version_id)
        .filter(ScanManifest.scan_id == scan_id, QuestionBankVersion.client_id == client_id)
        .order_by(ScanManifest.question_id.asc())
        .all()
    )
    return [
        ManifestEntry(
            question_id=row.question_id,
            bank_version_id=row.bank_version_id,
            weight_at_scan=Decimal(row.weight_at_scan),
            state_at_scan=row.state_at_scan,
        )
        for row in rows
    ]


def _manifest_count(db: Session, scan_id: str, *, client_id: str) -> int:
    return (
        db.query(ScanManifest)
        .join(QuestionBankVersion, QuestionBankVersion.bank_version_id == ScanManifest.bank_version_id)
        .filter(ScanManifest.scan_id == scan_id, QuestionBankVersion.client_id == client_id)
        .count()
    )


def _progress_total_calls(db: Session, scan_run_id: str) -> int:
    progress = db.query(ScanProgress).filter(ScanProgress.scan_run_id == scan_run_id).first()
    return int(progress.total_calls) if progress else 0


def _response_body_for_run(
    db: Session,
    run: ScanRun,
    *,
    providers: tuple[str, ...],
    samples_per_cell: int,
    question_count: int,
    total_calls: int,
    manifest_hash: str | None,
) -> dict[str, Any]:
    if manifest_hash is None:
        manifest_entries = _manifest_entries(db, run.id, client_id=run.client_id)
        manifest_hash = build_scan_run_plan(
            source_scan_id=run.id,
            providers=providers,
            manifest_entries=manifest_entries,
            cost_budget_usd=Decimal(run.cost_budget_usd),
            latency_class=run.latency_class,
        ).manifest_hash
    return {
        "scan_run_id": run.id,
        "client_id": run.client_id,
        "status": run.status,
        "idempotency_key": run.idempotency_key,
        "methodology_version": run.methodology_version,
        "methodology_version_set_id": run.methodology_version_set_id,
        "providers": list(providers),
        "samples_per_cell": samples_per_cell,
        "question_count": question_count,
        "total_calls": total_calls,
        "cost_budget_usd": str(_money4(Decimal(run.cost_budget_usd))),
        "latency_class": run.latency_class,
        "scan_manifest_hash": manifest_hash,
    }


def _complete_idempotency(idempotency: IdempotencyKey, *, status_code: int, body: dict[str, Any]) -> None:
    idempotency.response_status = status_code
    idempotency.response_body = body
    idempotency.completed_at = _utcnow()


def _active_methodology_version_set(db: Session) -> MethodologyVersionSet:
    now = _utcnow()
    version_set = (
        db.query(MethodologyVersionSet)
        .filter(MethodologyVersionSet.valid_from <= now)
        .filter(or_(MethodologyVersionSet.valid_to.is_(None), MethodologyVersionSet.valid_to > now))
        .order_by(MethodologyVersionSet.valid_from.desc())
        .first()
    )
    if not version_set:
        raise ScanRunKickoffError("Active methodology version set not found", status_code=409)
    return version_set


def _write_scan_run_audit(
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
        actor_type="user",
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
        raise ScanRunKickoffError("Audit HMAC key is not configured", status_code=500)
    return b"aiso-local-dev-audit-key"


def _audit_hmac_key_version() -> int:
    return int(os.getenv("AISO_AUDIT_HMAC_KEY_VERSION", "1"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _money4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"))
