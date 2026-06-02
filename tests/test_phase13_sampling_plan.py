from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.sampling import SamplingPlanError, prepare_sample_plan
from api.database import (
    AuditEvent,
    Base,
    Client,
    ExecutionSample,
    MethodologyVersionSet,
    QuestionBankQuestion,
    QuestionBankVersion,
    ScanManifest,
    ScanProgress,
    ScanRun,
    ScanStep,
    User,
)
from api.domain.sampling import (
    SAMPLES_PER_CELL,
    SAMPLING_CONFIG_VERSION,
    SAMPLING_TEMPERATURE,
    SAMPLING_TOP_P,
    deterministic_seed,
    provider_idempotency_key,
)


SCAN_RUN_ID = "33333333-3333-4333-8333-333333333333"
IDEMPOTENCY_KEY = "11111111-1111-4111-8111-111111111111"
METHODOLOGY_VERSION = "AVS-1.0.0+N-sampling-1.0.0+classifier-1.0.0"


def test_phase_13_6_acceptance_prepares_deterministic_n5_sample_plan():
    engine, Session = _sessionmaker()
    session = Session()
    try:
        _seed_scan_with_manifest(session)
        session.commit()

        result = prepare_sample_plan(session, scan_run_id=SCAN_RUN_ID, actor_id="system")
        replay = prepare_sample_plan(session, scan_run_id=SCAN_RUN_ID, actor_id="system")
        session.commit()

        assert result.question_count == 50
        assert result.provider_count == 2
        assert result.samples_per_cell == SAMPLES_PER_CELL
        assert result.planned_sample_count == 500
        assert result.inserted_sample_count == 500
        assert replay.inserted_sample_count == 0
        assert session.query(ExecutionSample).count() == 500
        assert session.query(ScanStep).filter_by(step_id="prepare_question_plan", event="succeeded").count() == 1
        assert [event.action for event in session.query(AuditEvent).all()] == [
            "scan_run.sample_plan_prepared"
        ]

        first = (
            session.query(ExecutionSample)
            .filter_by(scan_run_id=SCAN_RUN_ID, question_id="question-00", provider="openai", sample_index=0)
            .one()
        )
        assert first.seed == deterministic_seed(
            scan_id=SCAN_RUN_ID,
            question_id="question-00",
            provider="openai",
            sample_index=0,
        )
        assert first.provider_idem_key == provider_idempotency_key(
            scan_id=SCAN_RUN_ID,
            question_id="question-00",
            provider="openai",
            sample_index=0,
        )
        assert Decimal(first.temperature) == SAMPLING_TEMPERATURE
        assert Decimal(first.top_p) == SAMPLING_TOP_P
        assert first.planned_provider_model
        assert first.provider_model is None
        assert first.methodology_version == METHODOLOGY_VERSION
        assert first.cache_bust["scan_id"] == SCAN_RUN_ID
        assert first.cache_bust["uuid"]
        assert len(first.sample_plan_hash) == 32
        assert first.request_payload_hash is None
        assert first.raw_response is None
        assert first.raw_response_text is None
        assert first.raw_response_hash is None

        claude_first = (
            session.query(ExecutionSample)
            .filter_by(scan_run_id=SCAN_RUN_ID, question_id="question-00", provider="claude", sample_index=0)
            .one()
        )
        assert claude_first.seed is None
        assert claude_first.planned_provider_model
        assert claude_first.provider_model is None
        assert claude_first.provider_idem_key == provider_idempotency_key(
            scan_id=SCAN_RUN_ID,
            question_id="question-00",
            provider="claude",
            sample_index=0,
        )

        sample_indexes = {
            row.sample_index
            for row in session.query(ExecutionSample).filter_by(
                scan_run_id=SCAN_RUN_ID,
                question_id="question-00",
                provider="openai",
            )
        }
        assert sample_indexes == {0, 1, 2, 3, 4}

        progress = session.query(ScanProgress).one()
        assert progress.stage == "sample_plan_prepared"
        assert progress.total_calls == 500
        assert progress.per_provider["openai"]["planned"] == 250
        assert progress.per_provider["openai"]["last_status"] == "sample_plan_prepared"
        assert "gemini" not in progress.per_provider
    finally:
        session.close()
        engine.dispose()


def test_sample_plan_rejects_progress_total_drift_before_writing_samples():
    engine, Session = _sessionmaker()
    session = Session()
    try:
        _seed_scan_with_manifest(session)
        session.query(ScanProgress).filter_by(scan_run_id=SCAN_RUN_ID).one().total_calls = 999
        session.commit()

        with pytest.raises(SamplingPlanError) as exc_info:
            prepare_sample_plan(session, scan_run_id=SCAN_RUN_ID, actor_id="system")

        assert exc_info.value.status_code == 409
        assert "total_calls" in str(exc_info.value)
        assert session.query(ExecutionSample).count() == 0
        assert session.query(ScanStep).filter_by(step_id="prepare_question_plan").count() == 0
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


def _seed_scan_with_manifest(session) -> None:
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
            cost_budget_usd=Decimal("12.3400"),
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
            total_calls=500,
            completed_calls=0,
            failed_calls=0,
            per_provider={
                "openai": {"completed": 0, "failed": 0, "rate_limited": 0, "last_status": "queued"},
                "claude": {"completed": 0, "failed": 0, "rate_limited": 0, "last_status": "queued"},
                "gemini": {"completed": 0, "failed": 0, "rate_limited": 0, "last_status": "queued"},
            },
        )
    )
    bank_version = QuestionBankVersion(
        bank_version_id="bank-1",
        client_id="client-1",
        avs_version="AVS-1.0.0",
        effective_from=datetime.now(timezone.utc),
        n_core=35,
        n_tail=15,
        n_total=50,
        rotation_reason="phase12_initial_import",
    )
    session.add(bank_version)
    for index in range(50):
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
                state_at_scan="FROZEN" if index < 35 else "TAIL",
            )
        )
