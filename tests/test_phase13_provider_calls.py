from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.audit_log import verify_audit_chain
from api.adapters import scan_execution
from api.adapters.scan_runs import dashboard_projection_for_scan_run
from api.adapters.provider_calls import execute_provider_samples
from api.adapters.sampling import prepare_sample_plan
from api.database import (
    AuditEvent,
    Base,
    Classification,
    Client,
    CostLedgerEntry,
    AVSComputation,
    ExecutionSample,
    MethodologyVersionSet,
    MethodologyPromptVersion,
    QuestionBankQuestion,
    QuestionBankVersion,
    ScanManifest,
    ScanProgress,
    ScanProvenance,
    ScanRun,
    ScanStep,
    Sample,
    User,
)
from api.domain.ports import ProviderResponse
from api.domain.provider_calls import PROVIDER_MEASUREMENT_PROMPT_KEY, PROVIDER_MEASUREMENT_PROMPT_VERSION


SCAN_RUN_ID = "33333333-3333-4333-8333-333333333333"
IDEMPOTENCY_KEY = "11111111-1111-4111-8111-111111111111"
METHODOLOGY_VERSION = "AVS-1.0.0+N-sampling-1.0.0+classifier-1.0.0"


class RecordingProvider:
    def __init__(self, provider: str, *, cost_usd: float = 0.001, response_text: str | None = None):
        self.provider = provider
        self.cost_usd = cost_usd
        self.response_text = response_text
        self.calls: list[dict] = []

    async def complete(
        self,
        *,
        prompt: str,
        seed: int | None,
        temperature: float,
        top_p: float,
        idempotency_key: str,
    ) -> ProviderResponse:
        self.calls.append(
            {
                "prompt": prompt,
                "seed": seed,
                "temperature": temperature,
                "top_p": top_p,
                "idempotency_key": idempotency_key,
            }
        )
        return ProviderResponse(
            text=self.response_text or f"{self.provider} answer for {idempotency_key}",
            provider=self.provider,
            model=f"{self.provider}-actual-model",
            cost_usd=self.cost_usd,
            raw_metadata={"authorization": "secret", "safe": {"value": "ok"}},
            system_fingerprint=f"{self.provider}-fingerprint",
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            latency_ms=123,
            response_received_at=datetime(2026, 5, 24, 12, 5, tzinfo=timezone.utc),
        )


class RecordingClassifierJudge:
    def __init__(self):
        self.calls: list[dict] = []

    async def complete(
        self,
        *,
        prompt: str,
        seed: int | None,
        temperature: float,
        top_p: float,
        idempotency_key: str,
    ) -> ProviderResponse:
        self.calls.append(
            {
                "prompt": prompt,
                "seed": seed,
                "temperature": temperature,
                "top_p": top_p,
                "idempotency_key": idempotency_key,
            }
        )
        return ProviderResponse(
            text='{"label":"C+","rationale":"brand is listed"}',
            provider="claude",
            model="claude-sonnet-4-test",
        )


def test_phase_13_7_acceptance_executes_provider_samples_idempotently_and_records_costs():
    engine, Session = _sessionmaker()
    session = Session()
    openai = RecordingProvider("openai")
    claude = RecordingProvider("claude")
    try:
        _seed_scan_with_manifest(session)
        session.commit()
        prepare_sample_plan(session, scan_run_id=SCAN_RUN_ID, actor_id="system")
        session.commit()

        result = _run(
            execute_provider_samples(
                session,
                scan_run_id=SCAN_RUN_ID,
                provider_clients={"openai": openai, "claude": claude},
                actor_id="system",
            )
        )
        replay = _run(
            execute_provider_samples(
                session,
                scan_run_id=SCAN_RUN_ID,
                provider_clients={"openai": openai, "claude": claude},
                actor_id="system",
            )
        )
        session.commit()

        assert result.planned_count == 20
        assert result.executed_count == 20
        assert result.failed_count == 0
        assert result.completed_calls == 20
        assert result.failed_calls == 0
        assert result.stage == "provider_calls_completed"
        assert replay.already_recorded is True
        assert replay.executed_count == 0
        assert len(openai.calls) == 10
        assert len(claude.calls) == 10
        assert any(call["seed"] is None for call in claude.calls)
        assert all(call["top_p"] == 1.0 for call in openai.calls + claude.calls)

        first = (
            session.query(ExecutionSample)
            .filter_by(scan_run_id=SCAN_RUN_ID, question_id="question-00", provider="openai", sample_index=0)
            .one()
        )
        assert first.planned_provider_model
        assert first.provider_model == "openai-actual-model"
        assert first.raw_response_text.startswith("openai answer")
        assert first.raw_response_pointer is None
        assert len(first.request_payload_hash) == 32
        assert len(first.raw_response_hash) == 32
        assert first.system_fingerprint == "openai-fingerprint"
        assert first.input_tokens == 10
        assert first.output_tokens == 20
        assert first.total_tokens == 30
        assert first.latency_ms == 123
        assert first.failure_reason is None
        assert first.raw_response["metadata"]["authorization"] == "[redacted]"
        assert first.raw_response["metadata"]["safe"]["value"] == "ok"

        ledgers = {
            row.provider: Decimal(row.spent_usd)
            for row in session.query(CostLedgerEntry).order_by(CostLedgerEntry.provider.asc())
        }
        assert ledgers == {"claude": Decimal("0.010000"), "openai": Decimal("0.010000")}
        assert Decimal(session.query(ScanRun).one().cost_spent_usd) == Decimal("0.0200")
        progress = session.query(ScanProgress).one()
        assert progress.stage == "provider_calls_completed"
        assert progress.completed_calls == 20
        assert progress.failed_calls == 0
        assert progress.per_provider["openai"]["completed"] == 10
        assert progress.per_provider["claude"]["completed"] == 10
        assert session.query(ScanStep).filter_by(step_id="provider_calls", event="succeeded").count() == 1
        prompt_row = session.query(MethodologyPromptVersion).one()
        assert prompt_row.prompt_key == PROVIDER_MEASUREMENT_PROMPT_KEY
        assert prompt_row.version == PROVIDER_MEASUREMENT_PROMPT_VERSION
        assert len(prompt_row.prompt_hash) == 64
        assert len(prompt_row.chain_hash) == 64
        assert [event.action for event in session.query(AuditEvent).order_by(AuditEvent.id.asc()).all()] == [
            "scan_run.sample_plan_prepared",
            "scan_run.provider_calls_completed",
        ]
    finally:
        session.close()
        engine.dispose()


def test_provider_execution_records_missing_provider_as_failed_sample_without_throwing():
    engine, Session = _sessionmaker()
    session = Session()
    openai = RecordingProvider("openai")
    try:
        _seed_scan_with_manifest(session)
        session.commit()
        prepare_sample_plan(session, scan_run_id=SCAN_RUN_ID, actor_id="system")
        session.commit()

        result = _run(
            execute_provider_samples(
                session,
                scan_run_id=SCAN_RUN_ID,
                provider_clients={"openai": openai},
                actor_id="system",
            )
        )
        session.commit()

        assert result.planned_count == 20
        assert result.executed_count == 10
        assert result.failed_count == 10
        assert result.completed_calls == 10
        assert result.failed_calls == 10
        assert result.stage == "provider_calls_completed"
        assert len(openai.calls) == 10
        failed = (
            session.query(ExecutionSample)
            .filter_by(scan_run_id=SCAN_RUN_ID, provider="claude")
            .order_by(ExecutionSample.question_id.asc(), ExecutionSample.sample_index.asc())
            .first()
        )
        assert failed.raw_response_text is None
        assert failed.raw_response is None
        assert failed.raw_response_hash is None
        assert failed.request_payload_hash is not None
        assert failed.failure_reason == "Provider adapter is not configured: claude"
        assert session.query(ScanStep).filter_by(step_id="provider_calls", event="succeeded").count() == 1
    finally:
        session.close()
        engine.dispose()


def test_provider_execution_stops_before_calls_when_cost_budget_is_exhausted():
    engine, Session = _sessionmaker()
    session = Session()
    openai = RecordingProvider("openai")
    claude = RecordingProvider("claude")
    try:
        _seed_scan_with_manifest(session, cost_budget_usd=Decimal("0.0000"))
        session.commit()
        prepare_sample_plan(session, scan_run_id=SCAN_RUN_ID, actor_id="system")
        session.commit()

        result = _run(
            execute_provider_samples(
                session,
                scan_run_id=SCAN_RUN_ID,
                provider_clients={"openai": openai, "claude": claude},
                actor_id="system",
            )
        )
        session.commit()

        assert result.budget_exhausted is True
        assert result.executed_count == 0
        assert result.failed_count == 20
        assert result.completed_calls == 0
        assert result.failed_calls == 20
        assert len(openai.calls) == 0
        assert len(claude.calls) == 0
        run = session.query(ScanRun).one()
        progress = session.query(ScanProgress).one()
        assert run.status == "partial"
        assert run.completeness == "partial_degraded"
        assert progress.status == "partial"
        assert progress.stage == "provider_calls_completed"
        assert {
            sample.failure_reason
            for sample in session.query(ExecutionSample).filter_by(scan_run_id=SCAN_RUN_ID).all()
        } == {"cost_budget_exhausted"}
    finally:
        session.close()
        engine.dispose()


def test_provider_execution_stores_oversized_raw_response_by_pointer(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    large_text = "x" * (70 * 1024)
    claude = RecordingProvider("claude", response_text=large_text)
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_with_manifest(session)
        session.commit()
        prepare_sample_plan(session, scan_run_id=SCAN_RUN_ID, actor_id="system")
        session.commit()

        result = _run(
            execute_provider_samples(
                session,
                scan_run_id=SCAN_RUN_ID,
                provider_clients={"claude": claude},
                actor_id="system",
                limit=1,
            )
        )
        session.commit()

        assert result.executed_count == 1
        sample = (
            session.query(ExecutionSample)
            .filter_by(scan_run_id=SCAN_RUN_ID, provider="claude", question_id="question-00", sample_index=0)
            .one()
        )
        assert sample.raw_response_text is None
        assert sample.raw_response_pointer
        assert len(sample.raw_response_hash) == 32
        pointer_path = Path(sample.raw_response_pointer)
        if not pointer_path.is_absolute():
            pointer_path = Path.cwd() / pointer_path
        assert pointer_path.read_text(encoding="utf-8") == large_text
    finally:
        session.close()
        engine.dispose()


def test_scan_orchestrator_task_runs_provider_execution_through_registry(monkeypatch):
    engine, Session = _sessionmaker()
    openai = RecordingProvider("openai")
    claude = RecordingProvider("claude")
    classifier_judge = RecordingClassifierJudge()
    seed = Session()
    try:
        _seed_scan_with_manifest(seed)
        seed.commit()
    finally:
        seed.close()

    monkeypatch.setattr(scan_execution, "SessionLocal", Session)
    monkeypatch.setattr(
        scan_execution,
        "default_provider_clients",
        lambda: {"openai": openai, "claude": claude},
    )
    monkeypatch.setattr(scan_execution, "default_classifier_judge", lambda: classifier_judge)

    try:
        _run(
            scan_execution.scan_orchestrator_task(
                scan_run_id=SCAN_RUN_ID,
                idempotency_key=IDEMPOTENCY_KEY,
                methodology_version=METHODOLOGY_VERSION,
                cost_budget_usd="12.3400",
            )
        )
        session = Session()
        try:
            assert len(openai.calls) == 10
            assert len(claude.calls) == 10
            assert len(classifier_judge.calls) == 60
            progress = session.query(ScanProgress).one()
            assert progress.stage == "published"
            assert progress.completed_calls == 20
            run = session.query(ScanRun).one()
            assert run.status == "succeeded"
            assert run.completeness == "complete"
            assert session.query(ExecutionSample).filter(ExecutionSample.raw_response_hash.is_not(None)).count() == 20
            assert session.query(Sample).count() == 20
            assert session.query(Classification).count() == 40
            assert session.query(ScanProvenance).count() == 1
            assert session.query(AVSComputation).count() == 1
            assert session.query(ScanStep).filter_by(step_id="scan_orchestrator", event="started").count() == 1
            assert session.query(ScanStep).filter_by(step_id="prepare_question_plan", event="succeeded").count() == 1
            assert session.query(ScanStep).filter_by(step_id="provider_calls", event="succeeded").count() == 1
            assert session.query(ScanStep).filter_by(step_id="classify_samples", event="succeeded").count() == 1
            assert session.query(ScanStep).filter_by(step_id="compute_avs", event="succeeded").count() == 1
            assert session.query(ScanStep).filter_by(step_id="publish_scan", event="succeeded").count() == 1
            assert session.query(ScanStep).filter_by(step_id="compute_cai").count() == 0
            projection = dashboard_projection_for_scan_run(session, scan_run_id=SCAN_RUN_ID, user_id="user-1")
            assert projection is not None
            assert projection["status"] == "succeeded"
            assert projection["stage"] == "published"
            assert projection["avs"] is not None
            assert "cai" not in projection
            assert "coverage" not in projection
            assert "authority" not in projection
            assert "recency" not in projection
            actions = [event.action for event in session.query(AuditEvent).order_by(AuditEvent.id.asc()).all()]
            assert "scan.published" in actions
            assert "compute_cai.skipped" not in actions
            assert verify_audit_chain(session, hmac_keys={1: b"aiso-local-dev-audit-key"}) == []
        finally:
            session.close()
    finally:
        engine.dispose()


def _sessionmaker():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _seed_scan_with_manifest(session, *, cost_budget_usd: Decimal = Decimal("12.3400")) -> None:
    session.add(User(id="user-1", email="founder@example.com"))
    session.add(
        MethodologyVersionSet(
            id="mvs-1",
            label="phase13-test-current",
            avs_formula_version="AVS-1.0.0",
            bank_version="question-bank-1.0.0",
            stance_classifier_version="classifier-1.0.0",
            source_classifier_version="classifier-1.0.0",
            sampling_config_version="N-sampling-1.0.0",
            provider_model_snapshot_version="providers-1.0.0",
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            sys_period="current",
            spec_document_url="methodology/MANIFEST.txt",
            spec_document_hash=b"0" * 32,
            approved_by="founder",
            approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        Client(
            id="client-1",
            user_id="user-1",
            name="VectorCRM",
            url="https://vector.example",
            cost_budget_default_usd=Decimal("5.00"),
        )
    )
    session.add(
        ScanRun(
            id=SCAN_RUN_ID,
            client_id="client-1",
            idempotency_key=IDEMPOTENCY_KEY,
            methodology_version=METHODOLOGY_VERSION,
            methodology_version_set_id="mvs-1",
            status="running",
            cost_budget_usd=cost_budget_usd,
            cost_spent_usd=Decimal("0"),
            latency_class="standard",
            providers=["openai", "claude"],
            enqueued_at=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
            started_at=datetime(2026, 5, 24, 12, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        ScanProgress(
            scan_run_id=SCAN_RUN_ID,
            status="running",
            stage="preparing_question_plan",
            total_calls=20,
            completed_calls=0,
            failed_calls=0,
            per_provider={
                "openai": {"completed": 0, "failed": 0, "rate_limited": 0, "last_status": "queued"},
                "claude": {"completed": 0, "failed": 0, "rate_limited": 0, "last_status": "queued"},
            },
        )
    )
    bank_version = QuestionBankVersion(
        bank_version_id="bank-1",
        client_id="client-1",
        avs_version="AVS-1.0.0",
        effective_from=datetime.now(timezone.utc),
        n_core=2,
        n_tail=0,
        n_total=2,
        rotation_reason="phase12_initial_import",
    )
    session.add(bank_version)
    for index in range(2):
        question_id = f"question-{index:02d}"
        session.add(
            QuestionBankQuestion(
                question_id=question_id,
                client_id="client-1",
                text=f"What should buyers evaluate for VectorCRM option {index}?",
                text_hash=f"hash-{index:02d}",
                journey_stage="J2",
                brand_frame="U",
                locality="L0",
                source="generated",
            )
        )
        session.add(
            ScanManifest(
                scan_id=SCAN_RUN_ID,
                question_id=question_id,
                bank_version_id=bank_version.bank_version_id,
                weight_at_scan=Decimal("1.0000"),
                state_at_scan="FROZEN",
            )
        )


def _run(awaitable):
    import asyncio

    return asyncio.run(awaitable)
