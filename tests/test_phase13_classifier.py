from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.classifier import ClassificationExecutionError, execute_sample_classifications
from api.database import (
    AuditEvent,
    Base,
    Classification,
    Client,
    CostLedgerEntry,
    DomainClassification,
    ExecutionSample,
    MethodologyPromptVersion,
    MethodologyVersionSet,
    QuestionBankQuestion,
    QuestionBankVersion,
    Sample,
    ScanManifest,
    ScanProgress,
    ScanRawResponseArchive,
    ScanRun,
    ScanStep,
    User,
)
from api.domain.classifier import CLASSIFIER_VERSION, SOURCE_PROMPT_KEY, STANCE_PROMPT_KEY
from api.domain.ports import ProviderResponse


SCAN_RUN_ID = "33333333-3333-4333-8333-333333333333"
IDEMPOTENCY_KEY = "11111111-1111-4111-8111-111111111111"
METHODOLOGY_VERSION = "AVS-1.0.0+N-sampling-1.0.0+classifier-1.0.0"


class RecordingJudge:
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
        if "DOMAIN:" in prompt:
            text = '{"class":"EARNED-MID","rationale":"trade or editorial source"}'
        else:
            labels = ["R+", "R+", "C+"]
            index = (len([call for call in self.calls if "DOMAIN:" not in call["prompt"]]) - 1) % 3
            text = f'{{"label":"{labels[index]}","rationale":"VectorCRM is recommended"}}'
        return ProviderResponse(
            text=text,
            provider="claude",
            model="claude-sonnet-4-test",
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
            latency_ms=50,
            cost_usd=0.001,
        )


class FailingJudge:
    async def complete(
        self,
        *,
        prompt: str,
        seed: int | None,
        temperature: float,
        top_p: float,
        idempotency_key: str,
    ) -> ProviderResponse:
        raise RuntimeError("classifier unavailable")


def test_phase_13_8_acceptance_classifies_successful_samples_idempotently_and_records_provenance(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    judge = RecordingJudge()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_with_successful_samples(session)
        session.commit()

        result = _run(
            execute_sample_classifications(
                session,
                scan_run_id=SCAN_RUN_ID,
                judge_provider=judge,
                actor_id="system",
            )
        )
        replay = _run(
            execute_sample_classifications(
                session,
                scan_run_id=SCAN_RUN_ID,
                judge_provider=judge,
                actor_id="system",
            )
        )
        session.commit()

        assert result.successful_sample_count == 2
        assert result.canonical_sample_count == 2
        assert result.stance_classification_count == 2
        assert result.source_classification_count == 2
        assert result.stage == "classification_completed"
        assert replay.already_recorded is True
        assert len(judge.calls) == 7
        assert len([call for call in judge.calls if "DOMAIN:" not in call["prompt"]]) == 6
        assert len([call for call in judge.calls if "DOMAIN:" in call["prompt"]]) == 1
        assert all(call["temperature"] == 0.3 for call in judge.calls)
        assert all(call["prompt"].startswith("AISO_CLASSIFIER_PROMPT_V1:") for call in judge.calls)

        canonical_samples = session.query(Sample).order_by(Sample.question_id.asc()).all()
        assert len(canonical_samples) == 2
        assert all(sample.raw_response_hash for sample in canonical_samples)

        stance_rows = (
            session.query(Classification)
            .filter_by(classifier_type="stance")
            .order_by(Classification.sample_id.asc())
            .all()
        )
        assert len(stance_rows) == 2
        assert {row.consensus_value for row in stance_rows} == {"R+"}
        assert {Decimal(row.consensus_confidence) for row in stance_rows} == {Decimal("0.7500")}
        assert all(row.self_consistency_n == 3 for row in stance_rows)
        assert all(row.classifier_version == CLASSIFIER_VERSION for row in stance_rows)
        assert all(len(row.prompt_hash) == 32 for row in stance_rows)

        source_rows = session.query(Classification).filter_by(classifier_type="source").all()
        assert len(source_rows) == 2
        assert {row.consensus_value for row in source_rows} == {"OWNED"}
        assert all(any(item["source_class"] == "UGC" for item in row.individual_judgments) for row in source_rows)
        assert any(
            item["domain"] == "industrynews.example" and item["source_class"] == "EARNED-MID"
            for row in source_rows
            for item in row.individual_judgments
        )

        cache_rows = {row.domain: row for row in session.query(DomainClassification).all()}
        assert cache_rows["reddit.com"].source == "static_seed"
        assert cache_rows["industrynews.example"].source == "llm_fallback"
        assert cache_rows["industrynews.example"].expires_at is not None
        assert all(row.classifier_version == CLASSIFIER_VERSION for row in cache_rows.values())

        prompt_keys = {row.prompt_key for row in session.query(MethodologyPromptVersion).all()}
        assert {STANCE_PROMPT_KEY, SOURCE_PROMPT_KEY}.issubset(prompt_keys)
        assert session.query(ScanRawResponseArchive).count() == 1
        raw_archive = session.query(ScanRawResponseArchive).one()
        archive_path = Path(raw_archive.archive_url)
        if not archive_path.is_absolute():
            archive_path = Path.cwd() / archive_path
        assert archive_path.exists()
        archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
        assert len(archive_payload) == 2
        assert all(item["raw_response_text"].startswith("VectorCRM is a strong choice") for item in archive_payload)
        assert len(raw_archive.archive_hash) == 32

        samples = session.query(ExecutionSample).order_by(ExecutionSample.question_id.asc()).all()
        assert [sample.classified_stance for sample in samples] == ["R+", "R+"]
        assert [sample.classified_source for sample in samples] == ["OWNED", "OWNED"]
        classifier_ledger = session.query(CostLedgerEntry).filter_by(provider="claude_classifier").one()
        assert Decimal(classifier_ledger.spent_usd) == Decimal("0.007000")
        assert Decimal(session.query(ScanRun).one().cost_spent_usd) == Decimal("0.0070")
        assert session.query(ScanStep).filter_by(step_id="classify_samples", event="succeeded").count() == 1
        assert session.query(ScanProgress).one().stage == "classification_completed"
        assert [event.action for event in session.query(AuditEvent).order_by(AuditEvent.id.asc()).all()] == [
            "scan_run.samples_classified"
        ]
    finally:
        session.close()
        engine.dispose()


def test_classifier_failure_records_retryable_failed_step_and_raises(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_with_successful_samples(session)
        session.commit()

        with pytest.raises(ClassificationExecutionError):
            _run(
                execute_sample_classifications(
                    session,
                    scan_run_id=SCAN_RUN_ID,
                    judge_provider=FailingJudge(),
                    actor_id="system",
                    limit=1,
                )
            )
        session.commit()

        progress = session.query(ScanProgress).one()
        run = session.query(ScanRun).one()
        assert progress.stage == "classification_failed"
        assert run.error_summary["retryable"] is True
        failed_step = session.query(ScanStep).filter_by(step_id="classify_samples", event="failed").one()
        assert failed_step.payload["retryable"] is True
        assert session.query(ScanStep).filter_by(step_id="classify_samples", event="succeeded").count() == 0
        assert [event.action for event in session.query(AuditEvent).order_by(AuditEvent.id.asc()).all()] == [
            "scan.classifier.gate_failure"
        ]
    finally:
        session.close()
        engine.dispose()


def test_source_cache_is_scoped_to_classifier_version(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    judge = RecordingJudge()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_with_successful_samples(session)
        session.add(
            DomainClassification(
                domain="industrynews.example",
                classifier_version="classifier-0.9.0",
                source_class="UNKNOWN",
                classifier_model="old-model",
                confidence=Decimal("0.4000"),
                source="old_cache",
            )
        )
        session.commit()

        _run(
            execute_sample_classifications(
                session,
                scan_run_id=SCAN_RUN_ID,
                judge_provider=judge,
                actor_id="system",
                limit=1,
            )
        )
        session.commit()

        assert len([call for call in judge.calls if "DOMAIN:" in call["prompt"]]) == 1
        rows = {
            (row.domain, row.classifier_version): row
            for row in session.query(DomainClassification).filter_by(domain="industrynews.example").all()
        }
        assert rows[("industrynews.example", "classifier-0.9.0")].source_class == "UNKNOWN"
        assert rows[("industrynews.example", CLASSIFIER_VERSION)].source_class == "EARNED-MID"
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


def _seed_scan_with_successful_samples(session) -> None:
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
            owned_domains=["vector.example"],
            competitor_domains=["rivalcrm.example"],
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
            providers=["openai"],
            enqueued_at=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
            started_at=datetime(2026, 5, 24, 12, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        ScanProgress(
            scan_run_id=SCAN_RUN_ID,
            status="running",
            stage="provider_calls_completed",
            total_calls=2,
            completed_calls=2,
            failed_calls=0,
            per_provider={
                "openai": {"completed": 2, "failed": 0, "rate_limited": 0, "last_status": "provider_calls_completed"},
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
        raw_text = (
            "VectorCRM is a strong choice for sales teams. "
            "See [VectorCRM](https://vector.example/features), "
            "[Reddit](https://reddit.com/r/crm/comments/abc), and "
            "[IndustryNews](https://industrynews.example/review)."
        )
        session.add(
            ExecutionSample(
                scan_run_id=SCAN_RUN_ID,
                question_id=question_id,
                provider="openai",
                sample_index=0,
                planned_provider_model="gpt-test",
                provider_model="gpt-test-actual",
                temperature=Decimal("0.700"),
                top_p=Decimal("1.000"),
                seed=100 + index,
                request_payload_hash=b"r" * 32,
                raw_response={"metadata": {"citations": []}},
                raw_response_text=raw_text,
                raw_response_hash=hashlib.sha256(raw_text.encode("utf-8")).digest(),
                system_fingerprint="fp-test",
                cost_usd=Decimal("0.001000"),
                provider_idem_key=f"sample-{index}",
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                response_received_at=datetime(2026, 5, 24, 12, 5, tzinfo=timezone.utc),
                latency_ms=100,
                methodology_version=METHODOLOGY_VERSION,
                cache_bust={},
            )
        )


def _run(awaitable):
    import asyncio

    return asyncio.run(awaitable)
