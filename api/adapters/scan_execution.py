"""Execution adapters for the downstream scan engine.

This module owns framework and infrastructure concerns for execution-1.0:
Procrastinate queue enqueueing, SQLAlchemy saga step persistence, and the
thin task entrypoint that starts the orchestrated scan saga.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import os
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from api.adapters.audit_log import write_audit_event
from api.adapters.avs import compute_scan_avs
from api.adapters.classifier import default_classifier_judge, execute_sample_classifications
from api.adapters.execution_state import record_step_once, safe_error, scan_step
from api.adapters.provider_calls import execute_provider_samples
from api.adapters.provider_registry import default_provider_clients
from api.adapters.sampling import prepare_sample_plan
from api.database import AVSComputation, Scan, ScanProgress, ScanProvenance, ScanRun, SessionLocal
from api.domain.ports import ScanExecutor, ScanHandle


class ScanExecutionError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class ScanQueueConflict(ScanExecutionError):
    def __init__(self, message: str = "Client already has an active queued scan"):
        super().__init__(message, status_code=409)


@dataclass(frozen=True)
class EnqueueOutcome:
    handle: ScanHandle
    already_recorded: bool


@dataclass(frozen=True)
class PublishScanOutcome:
    scan_run_id: str
    status: str
    completeness: str
    already_recorded: bool


class ProcrastinateScanExecutor(ScanExecutor):
    """Procrastinate-backed implementation of the ScanExecutor port."""

    def __init__(
        self,
        *,
        app: Any,
        orchestrator_task: Any,
        already_enqueued_exception: type[BaseException] | tuple[type[BaseException], ...] | None = None,
    ) -> None:
        self.app = app
        self.orchestrator_task = orchestrator_task
        self.already_enqueued_exception = already_enqueued_exception
        self._opened = False

    async def enqueue(
        self,
        *,
        scan_run_id,
        idempotency_key: str,
        client_id,
        methodology_version: str,
        cost_budget_usd: float,
        priority: int = 0,
    ) -> ScanHandle:
        configured_task = self.orchestrator_task.configure(
            queueing_lock=f"scan:{client_id}",
            lock=f"client:{client_id}",
            priority=priority,
            schedule_in={"seconds": 0},
        )
        try:
            await configured_task.defer_async(
                scan_run_id=str(scan_run_id),
                idempotency_key=idempotency_key,
                methodology_version=methodology_version,
                cost_budget_usd=str(cost_budget_usd),
            )
        except Exception as exc:
            if self._is_already_enqueued(exc):
                raise ScanQueueConflict() from exc
            raise
        return ScanHandle(
            scan_run_id=_uuid(scan_run_id),
            idempotency_key=idempotency_key,
            enqueued_at=_utcnow(),
            methodology_version=methodology_version,
        )

    async def status(self, scan_run_id):
        raise NotImplementedError("Scan status is served by the SQLAlchemy progress adapter")

    async def cancel(self, scan_run_id, reason: str) -> None:
        raise NotImplementedError("Scan cancellation is implemented in a later Phase 13 slice")

    def _is_already_enqueued(self, exc: Exception) -> bool:
        if self.already_enqueued_exception and isinstance(exc, self.already_enqueued_exception):
            return True
        return exc.__class__.__name__ == "AlreadyEnqueued"

    def open(self) -> None:
        if self._opened:
            return
        open_app = getattr(self.app, "open", None)
        if open_app:
            open_app()
        self._opened = True

    def close(self) -> None:
        if not self._opened:
            return
        close_app = getattr(self.app, "close", None)
        if close_app:
            close_app()
        self._opened = False


async def ensure_scan_run_enqueued(
    db: Session,
    *,
    scan_run_id: str,
    actor_id: str,
    executor: ScanExecutor,
    priority: int = 0,
) -> EnqueueOutcome:
    run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).first()
    if not run:
        raise ScanExecutionError("Scan run not found", status_code=404)

    existing_step = scan_step(
        db,
        scan_run_id=scan_run_id,
        step_id="enqueue_scan",
        event="succeeded",
    )
    if existing_step:
        return EnqueueOutcome(handle=_handle_from_run(run), already_recorded=True)

    try:
        handle = await executor.enqueue(
            scan_run_id=run.id,
            idempotency_key=run.idempotency_key,
            client_id=run.client_id,
            methodology_version=run.methodology_version,
            cost_budget_usd=float(run.cost_budget_usd),
            priority=priority,
        )
    except Exception as exc:
        _record_enqueue_failure(
            db,
            run=run,
            actor_id=actor_id,
            priority=priority,
            exc=exc,
        )
        status_code = exc.status_code if isinstance(exc, ScanExecutionError) else 503
        raise ScanExecutionError(f"Scan enqueue failed: {exc}", status_code=status_code) from exc

    recorded = record_step_once(
        db,
        scan_run_id=run.id,
        step_id="enqueue_scan",
        event="succeeded",
        payload={
            "queue": "procrastinate",
            "client_id": run.client_id,
            "idempotency_key": run.idempotency_key,
            "methodology_version": run.methodology_version,
            "priority": priority,
        },
    )
    if not recorded:
        return EnqueueOutcome(handle=handle, already_recorded=True)
    _write_scan_execution_audit(
        db,
        actor_id=actor_id,
        action="scan_run.enqueued",
        resource_id=run.id,
        after_state={
            "scan_run_id": run.id,
            "client_id": run.client_id,
            "status": run.status,
            "methodology_version": run.methodology_version,
        },
        reason="Queued downstream scan run through ScanExecutor",
        correlation_id=run.idempotency_key,
    )
    db.flush()
    return EnqueueOutcome(handle=handle, already_recorded=False)


def start_scan_orchestrator(
    db: Session,
    *,
    scan_run_id: str,
    idempotency_key: str,
    methodology_version: str,
    cost_budget_usd: str | float,
) -> bool:
    """Start the parent scan saga exactly once.

    Publishing and notification are implemented in a later slice; this boundary
    establishes the mandatory saga-step idempotency from execution-1.0.
    """

    run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).first()
    if not run:
        raise ScanExecutionError("Scan run not found", status_code=404)
    if run.idempotency_key != idempotency_key:
        raise ScanExecutionError("Scan idempotency key mismatch", status_code=409)
    if run.methodology_version != methodology_version:
        raise ScanExecutionError("Scan methodology version mismatch", status_code=409)
    if _money4(Decimal(str(run.cost_budget_usd))) != _money4(Decimal(str(cost_budget_usd))):
        raise ScanExecutionError("Scan cost budget mismatch", status_code=409)

    existing_step = scan_step(
        db,
        scan_run_id=scan_run_id,
        step_id="scan_orchestrator",
        event="started",
    )
    if existing_step:
        return False

    recorded = record_step_once(
        db,
        scan_run_id=scan_run_id,
        step_id="scan_orchestrator",
        event="started",
        payload={
            "methodology_version": methodology_version,
            "cost_budget_usd": str(_money4(Decimal(str(cost_budget_usd)))),
        },
    )
    if not recorded:
        return False

    now = _utcnow()
    run.status = "running"
    run.started_at = run.started_at or now

    progress = db.query(ScanProgress).filter(ScanProgress.scan_run_id == scan_run_id).first()
    if progress:
        progress.status = "running"
        progress.stage = "preparing_question_plan"
        progress.updated_at = now

    _write_scan_execution_audit(
        db,
        actor_id="system",
        action="scan_run.orchestrator_started",
        resource_id=scan_run_id,
        after_state={
            "scan_run_id": scan_run_id,
            "status": "running",
            "stage": "preparing_question_plan",
        },
        reason="Started orchestrated scan saga",
        correlation_id=idempotency_key,
    )
    db.flush()
    return True


async def scan_orchestrator_task(
    *,
    scan_run_id: str,
    idempotency_key: str,
    methodology_version: str,
    cost_budget_usd: str,
) -> None:
    db = SessionLocal()
    try:
        start_scan_orchestrator(
            db,
            scan_run_id=scan_run_id,
            idempotency_key=idempotency_key,
            methodology_version=methodology_version,
            cost_budget_usd=cost_budget_usd,
        )
        db.commit()
        prepare_sample_plan(db, scan_run_id=scan_run_id, actor_id="system")
        db.commit()
        await execute_provider_samples(
            db,
            scan_run_id=scan_run_id,
            provider_clients=default_provider_clients(),
            actor_id="system",
        )
        db.commit()
        await execute_sample_classifications(
            db,
            scan_run_id=scan_run_id,
            judge_provider=default_classifier_judge(),
            actor_id="system",
        )
        db.commit()
        compute_scan_avs(
            db,
            scan_run_id=scan_run_id,
            actor_id="system",
        )
        db.commit()
        # CAI is intentionally deferred: AVS-1.0 names CAI but does not define
        # Coverage, Authority, or Recency sub-index formulas. The future
        # compute_cai saga step belongs here, between compute_avs and publish_scan.
        publish_scan(db, scan_run_id=scan_run_id, actor_id="system")
        db.commit()
    except Exception:
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


_DEFAULT_SCAN_EXECUTOR: ProcrastinateScanExecutor | None = None


def default_scan_executor() -> ScanExecutor:
    global _DEFAULT_SCAN_EXECUTOR
    if _DEFAULT_SCAN_EXECUTOR is None:
        _DEFAULT_SCAN_EXECUTOR = create_procrastinate_scan_executor()
        _DEFAULT_SCAN_EXECUTOR.open()
    return _DEFAULT_SCAN_EXECUTOR


def build_procrastinate_app() -> tuple[Any, Any]:
    """Construct the Procrastinate app and register the orchestrator task.

    Shared by the API-side executor (which defers jobs) and the worker
    entrypoint (`api/worker.py`, which consumes them). Both connect to the
    same PostgreSQL queue and register the task under the same name/queue so
    a deferred job is picked up by the worker.
    """
    try:
        import procrastinate
    except ImportError as exc:
        raise ScanExecutionError("Procrastinate is not installed") from exc

    connector = procrastinate.PsycopgConnector(conninfo=_procrastinate_database_url())
    app = procrastinate.App(connector=connector)
    task = app.task(name="scan_orchestrator_task", queue="scan_orchestrator")(scan_orchestrator_task)
    return app, task


def create_procrastinate_scan_executor() -> ProcrastinateScanExecutor:
    import procrastinate

    app, task = build_procrastinate_app()
    already_enqueued_exception = getattr(
        getattr(procrastinate, "exceptions", object()),
        "AlreadyEnqueued",
        None,
    )
    return ProcrastinateScanExecutor(
        app=app,
        orchestrator_task=task,
        already_enqueued_exception=already_enqueued_exception,
    )


def reset_default_scan_executor() -> None:
    global _DEFAULT_SCAN_EXECUTOR
    if _DEFAULT_SCAN_EXECUTOR is not None:
        _DEFAULT_SCAN_EXECUTOR.close()
    _DEFAULT_SCAN_EXECUTOR = None


def publish_scan(
    db: Session,
    *,
    scan_run_id: str,
    actor_id: str,
) -> PublishScanOutcome:
    run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).first()
    if not run:
        raise ScanExecutionError("Scan run not found", status_code=404)
    progress = db.query(ScanProgress).filter(ScanProgress.scan_run_id == scan_run_id).first()
    if not progress:
        raise ScanExecutionError("Scan progress not found", status_code=409)

    existing_step = scan_step(
        db,
        scan_run_id=run.id,
        step_id="publish_scan",
        event="succeeded",
    )
    if existing_step:
        return PublishScanOutcome(
            scan_run_id=run.id,
            status=run.status,
            completeness=run.completeness or "complete",
            already_recorded=True,
        )

    try:
        avs = (
            db.query(AVSComputation)
            .filter(
                AVSComputation.scan_id == run.id,
                AVSComputation.methodology_version_set_id == run.methodology_version_set_id,
                AVSComputation.is_primary.is_(True),
            )
            .one_or_none()
        )
        if avs is None:
            raise ScanExecutionError("Primary AVS computation must exist before publishing", status_code=409)
        provenance = db.query(ScanProvenance).filter(ScanProvenance.scan_id == run.id).one_or_none()
        if provenance is None:
            raise ScanExecutionError("Signed scan provenance must exist before publishing", status_code=409)

        completeness = run.completeness or "complete"
        run.status = "partial" if completeness == "partial_degraded" else "succeeded"
        run.finished_at = run.finished_at or _utcnow()
        progress.status = run.status
        progress.stage = "published"
        progress.updated_at = _utcnow()

        legacy_scan = db.query(Scan).filter(Scan.id == run.id, Scan.client_id == run.client_id).one_or_none()
        if legacy_scan:
            legacy_scan.status = "complete"
            legacy_scan.completed_at = legacy_scan.completed_at or run.finished_at

        recorded = record_step_once(
            db,
            scan_run_id=run.id,
            step_id="publish_scan",
            event="succeeded",
            payload={
                "status": run.status,
                "completeness": completeness,
                "methodology_version_set_id": run.methodology_version_set_id,
                "avs_computation_id": avs.id,
                "scan_provenance_hash": provenance.this_provenance_hash.hex(),
            },
        )
        if recorded:
            _write_scan_execution_audit(
                db,
                actor_id=actor_id,
                action="scan.published",
                resource_id=run.id,
                after_state={
                    "scan_run_id": run.id,
                    "client_id": run.client_id,
                    "status": run.status,
                    "completeness": completeness,
                    "stage": progress.stage,
                    "methodology_version_set_id": run.methodology_version_set_id,
                    "avs_computation_id": avs.id,
                },
                reason="Published scan dashboard projection after signed AVS computation",
                correlation_id=run.idempotency_key,
            )
    except ScanExecutionError as exc:
        record_step_once(
            db,
            scan_run_id=run.id,
            step_id="publish_scan",
            event="failed",
            payload={"reason": safe_error(exc)},
        )
        raise

    db.flush()
    return PublishScanOutcome(
        scan_run_id=run.id,
        status=run.status,
        completeness=run.completeness or "complete",
        already_recorded=False,
    )


def _procrastinate_database_url() -> str:
    database_url = os.getenv("PROCRASTINATE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url or database_url.startswith("sqlite"):
        raise ScanExecutionError("Procrastinate requires a PostgreSQL database URL")
    return (
        database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )


def _handle_from_run(run: ScanRun) -> ScanHandle:
    return ScanHandle(
        scan_run_id=_uuid(run.id),
        idempotency_key=run.idempotency_key,
        enqueued_at=run.enqueued_at,
        methodology_version=run.methodology_version,
    )


def _uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _record_enqueue_failure(
    db: Session,
    *,
    run: ScanRun,
    actor_id: str,
    priority: int,
    exc: Exception,
) -> None:
    reason = safe_error(exc)
    recorded = record_step_once(
        db,
        scan_run_id=run.id,
        step_id="enqueue_scan",
        event="failed",
        payload={
            "queue": "procrastinate",
            "client_id": run.client_id,
            "idempotency_key": run.idempotency_key,
            "methodology_version": run.methodology_version,
            "priority": priority,
            "reason": reason,
        },
    )
    if not recorded:
        return
    _write_scan_execution_audit(
        db,
        actor_id=actor_id,
        action="scan_run.enqueue_failed",
        resource_id=run.id,
        after_state={
            "scan_run_id": run.id,
            "client_id": run.client_id,
            "status": run.status,
            "reason": reason,
        },
        reason="Failed to queue downstream scan run",
        correlation_id=run.idempotency_key,
    )
    db.flush()


def _write_scan_execution_audit(
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
        raise ScanExecutionError("Audit HMAC key is not configured", status_code=500)
    return b"aiso-local-dev-audit-key"


def _audit_hmac_key_version() -> int:
    return int(os.getenv("AISO_AUDIT_HMAC_KEY_VERSION", "1"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _money4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"))
