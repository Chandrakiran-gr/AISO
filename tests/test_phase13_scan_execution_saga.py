import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.scan_execution import (
    ProcrastinateScanExecutor,
    ScanExecutionError,
    ScanQueueConflict,
    ensure_scan_run_enqueued,
    start_scan_orchestrator,
)
from api.database import AuditEvent, Base, Client, ScanProgress, ScanRun, ScanStep, User


SCAN_RUN_ID = "33333333-3333-4333-8333-333333333333"
IDEMPOTENCY_KEY = "11111111-1111-4111-8111-111111111111"
CLIENT_ID = "22222222-2222-4222-8222-222222222222"
METHODOLOGY_VERSION = "execution-1.0.0-test"


class AlreadyEnqueued(Exception):
    pass


class FakeProcrastinateTask:
    def __init__(self, *, exc: Exception | None = None):
        self.exc = exc
        self.configure_calls = []
        self.defer_calls = []

    def configure(self, **kwargs):
        self.configure_calls.append(kwargs)
        return self

    async def defer_async(self, **kwargs):
        self.defer_calls.append(kwargs)
        if self.exc:
            raise self.exc


class FakeProcrastinateApp:
    def __init__(self):
        self.open_count = 0
        self.close_count = 0

    def open(self):
        self.open_count += 1

    def close(self):
        self.close_count += 1


class ConflictScanExecutor:
    async def enqueue(
        self,
        *,
        scan_run_id,
        idempotency_key: str,
        client_id,
        methodology_version: str,
        cost_budget_usd: float,
        priority: int = 0,
    ):
        raise ScanQueueConflict()


def test_procrastinate_executor_uses_spec_locks_and_defer_payload():
    asyncio.run(_run_procrastinate_executor_uses_spec_locks_and_defer_payload())


async def _run_procrastinate_executor_uses_spec_locks_and_defer_payload():
    task = FakeProcrastinateTask()
    executor = ProcrastinateScanExecutor(app=FakeProcrastinateApp(), orchestrator_task=task)

    handle = await executor.enqueue(
        scan_run_id=UUID(SCAN_RUN_ID),
        idempotency_key=IDEMPOTENCY_KEY,
        client_id=UUID(CLIENT_ID),
        methodology_version=METHODOLOGY_VERSION,
        cost_budget_usd=12.34,
        priority=7,
    )

    assert str(handle.scan_run_id) == SCAN_RUN_ID
    assert task.configure_calls == [
        {
            "queueing_lock": f"scan:{CLIENT_ID}",
            "lock": f"client:{CLIENT_ID}",
            "priority": 7,
            "schedule_in": {"seconds": 0},
        }
    ]
    assert task.defer_calls == [
        {
            "scan_run_id": SCAN_RUN_ID,
            "idempotency_key": IDEMPOTENCY_KEY,
            "methodology_version": METHODOLOGY_VERSION,
            "cost_budget_usd": "12.34",
        }
    ]


def test_procrastinate_executor_fails_closed_on_ambiguous_already_enqueued():
    asyncio.run(_run_procrastinate_executor_fails_closed_on_ambiguous_already_enqueued())


async def _run_procrastinate_executor_fails_closed_on_ambiguous_already_enqueued():
    task = FakeProcrastinateTask(exc=AlreadyEnqueued("duplicate queueing lock"))
    executor = ProcrastinateScanExecutor(
        app=FakeProcrastinateApp(),
        orchestrator_task=task,
        already_enqueued_exception=AlreadyEnqueued,
    )

    with pytest.raises(ScanQueueConflict):
        await executor.enqueue(
            scan_run_id=UUID(SCAN_RUN_ID),
            idempotency_key=IDEMPOTENCY_KEY,
            client_id=UUID(CLIENT_ID),
            methodology_version=METHODOLOGY_VERSION,
            cost_budget_usd=12.34,
        )

    assert len(task.defer_calls) == 1


def test_procrastinate_executor_open_close_are_idempotent():
    app = FakeProcrastinateApp()
    executor = ProcrastinateScanExecutor(app=app, orchestrator_task=FakeProcrastinateTask())

    executor.open()
    executor.open()
    executor.close()
    executor.close()

    assert app.open_count == 1
    assert app.close_count == 1


def test_enqueue_failure_records_failed_saga_step_and_audit_event():
    engine, Session = _sessionmaker()
    session = Session()
    try:
        _seed_scan_run(session)
        session.commit()

        with pytest.raises(ScanExecutionError) as error:
            asyncio.run(
                ensure_scan_run_enqueued(
                    session,
                    scan_run_id=SCAN_RUN_ID,
                    actor_id="user-1",
                    executor=ConflictScanExecutor(),
                )
            )
        session.commit()

        assert error.value.status_code == 409
        assert session.query(ScanStep).filter_by(step_id="enqueue_scan", event="succeeded").count() == 0
        failed_step = session.query(ScanStep).filter_by(step_id="enqueue_scan", event="failed").one()
        assert failed_step.payload["reason"] == "Client already has an active queued scan"
        assert [event.action for event in session.query(AuditEvent).all()] == [
            "scan_run.enqueue_failed"
        ]
    finally:
        session.close()
        engine.dispose()


def test_scan_orchestrator_start_is_idempotent_and_updates_progress():
    engine, Session = _sessionmaker()
    session = Session()
    try:
        _seed_scan_run(session)
        session.commit()

        first = start_scan_orchestrator(
            session,
            scan_run_id=SCAN_RUN_ID,
            idempotency_key=IDEMPOTENCY_KEY,
            methodology_version=METHODOLOGY_VERSION,
            cost_budget_usd="12.3400",
        )
        second = start_scan_orchestrator(
            session,
            scan_run_id=SCAN_RUN_ID,
            idempotency_key=IDEMPOTENCY_KEY,
            methodology_version=METHODOLOGY_VERSION,
            cost_budget_usd="12.3400",
        )
        session.commit()

        assert first is True
        assert second is False
        run = session.query(ScanRun).one()
        assert run.status == "running"
        assert run.started_at is not None
        progress = session.query(ScanProgress).one()
        assert progress.status == "running"
        assert progress.stage == "preparing_question_plan"
        assert session.query(ScanStep).filter_by(step_id="scan_orchestrator", event="started").count() == 1
        assert [event.action for event in session.query(AuditEvent).all()] == [
            "scan_run.orchestrator_started"
        ]
    finally:
        session.close()
        engine.dispose()


def _sessionmaker():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _seed_scan_run(session) -> None:
    session.add(User(id="user-1", email="founder@example.com"))
    session.add(
        Client(
            id=CLIENT_ID,
            user_id="user-1",
            name="VectorCRM",
            url="https://vector.example",
            cost_budget_default_usd=Decimal("5.00"),
        )
    )
    session.add(
        ScanRun(
            id=SCAN_RUN_ID,
            client_id=CLIENT_ID,
            idempotency_key=IDEMPOTENCY_KEY,
            methodology_version=METHODOLOGY_VERSION,
            status="queued",
            cost_budget_usd=Decimal("12.3400"),
            cost_spent_usd=Decimal("0"),
            latency_class="standard",
            enqueued_at=datetime.now(timezone.utc),
        )
    )
    session.add(
        ScanProgress(
            scan_run_id=SCAN_RUN_ID,
            status="queued",
            stage="queued",
            total_calls=500,
            completed_calls=0,
            failed_calls=0,
            per_provider={},
        )
    )
