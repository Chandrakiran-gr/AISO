from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.avs import AVSComputationError, compute_scan_avs
from api.database import (
    AVSComputation,
    AuditEvent,
    Base,
    Classification,
    Client,
    ExecutionSample,
    MethodologyVersionSet,
    QuestionBankQuestion,
    QuestionBankVersion,
    Sample,
    Scan,
    ScanManifest,
    ScanProgress,
    ScanProvenance,
    ScanRawResponseArchive,
    ScanResult,
    ScanRun,
    ScanStep,
    User,
)
from api.domain.avs import (
    AVSSample,
    avs_from_subindices,
    compute_subindices,
    first_mention_position,
    normalized_aliases,
    wilson_interval,
)


SCAN_RUN_ID = "44444444-4444-4444-8444-444444444444"
IDEMPOTENCY_KEY = "11111111-1111-4111-8111-111111111111"
METHODOLOGY_VERSION = "AVS-1.0.0+N-sampling-1.0.0+classifier-1.0.0"


def test_phase_13_9_acceptance_computes_avs_signs_provenance_and_updates_legacy_projection(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_ready_for_avs(session, tmp_path=tmp_path)
        session.commit()

        result = compute_scan_avs(
            session,
            scan_run_id=SCAN_RUN_ID,
            actor_id="system",
            bootstrap_iterations=200,
            bootstrap_seed=7,
        )
        replay = compute_scan_avs(
            session,
            scan_run_id=SCAN_RUN_ID,
            actor_id="system",
            bootstrap_iterations=200,
            bootstrap_seed=7,
        )
        session.commit()

        assert result.already_recorded is False
        assert replay.already_recorded is True
        assert result.completeness == "complete"
        assert result.bootstrap_iterations == 200
        assert result.ci_method in {"BCa", "percentile-fallback"}

        expected_indices = compute_subindices(_expected_samples_by_pair(), target_aliases=["VectorCRM"])
        expected_avs = avs_from_subindices(expected_indices)
        assert result.presence == pytest.approx(expected_indices.presence, abs=0.00001)
        assert result.prominence == pytest.approx(expected_indices.prominence, abs=0.00001)
        assert result.positivity == pytest.approx(expected_indices.positivity, abs=0.00001)
        assert result.avs_value == pytest.approx(round(expected_avs, 3), abs=0.001)
        assert 0 <= result.ci_lower_95 <= result.avs_value <= result.ci_upper_95 <= 100

        computation = session.query(AVSComputation).one()
        assert Decimal(computation.avs_value) == Decimal(str(result.avs_value)).quantize(Decimal("0.001"))
        assert computation.is_primary is True
        assert computation.computed_by_git_sha == "unknown"

        provenance = session.query(ScanProvenance).one()
        raw_archive = session.query(ScanRawResponseArchive).one()
        assert provenance.raw_response_archive_hash == raw_archive.archive_hash
        assert provenance.sample_count == 10
        assert len(provenance.this_provenance_hash) == 32

        run = session.query(ScanRun).one()
        progress = session.query(ScanProgress).one()
        assert run.status == "succeeded"
        assert run.completeness == "complete"
        assert run.finished_at is not None
        assert progress.status == "succeeded"
        assert progress.stage == "avs_computed"
        assert session.query(ScanStep).filter_by(step_id="compute_avs", event="succeeded").count() == 1
        assert [event.action for event in session.query(AuditEvent).order_by(AuditEvent.id.asc()).all()] == [
            "scan_run.avs_computed"
        ]
        legacy = session.query(ScanResult).one()
        assert legacy.visibility_score == round(result.avs_value, 2)
    finally:
        session.close()
        engine.dispose()


def test_avs_zero_mentions_is_exact_zero_with_percentile_fallback(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_ready_for_avs(session, tmp_path=tmp_path, all_mentions=False)
        session.commit()

        result = compute_scan_avs(
            session,
            scan_run_id=SCAN_RUN_ID,
            actor_id="system",
            bootstrap_iterations=50,
        )
        session.commit()

        assert result.avs_value == 0
        assert result.presence == 0
        assert result.ci_lower_95 == 0
        assert result.ci_upper_95 == 0
        assert result.ci_method == "percentile-fallback"
    finally:
        session.close()
        engine.dispose()


def test_avs_rejects_corrupt_raw_archive_before_signing_provenance(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_ready_for_avs(session, tmp_path=tmp_path)
        archive = session.query(ScanRawResponseArchive).one()
        Path(archive.archive_url).write_text("tampered", encoding="utf-8")
        session.commit()

        with pytest.raises(AVSComputationError, match="hash mismatch"):
            compute_scan_avs(
                session,
                scan_run_id=SCAN_RUN_ID,
                actor_id="system",
                bootstrap_iterations=50,
            )
        run = session.query(ScanRun).one()
        progress = session.query(ScanProgress).one()
        assert run.status == "failed"
        assert progress.stage == "avs_failed"
        assert session.query(ScanProvenance).count() == 0
        assert session.query(AVSComputation).count() == 0
        assert session.query(ScanStep).filter_by(step_id="compute_avs", event="failed").count() == 1
    finally:
        session.close()
        engine.dispose()


def test_avs_rejects_missing_classifier_1_stance_classification(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_ready_for_avs(session, tmp_path=tmp_path)
        session.query(Classification).filter(Classification.sample_id == "sample-question-00-0").delete()
        session.commit()

        with pytest.raises(AVSComputationError, match="Missing classifier-1.0.0 stance classification"):
            compute_scan_avs(
                session,
                scan_run_id=SCAN_RUN_ID,
                actor_id="system",
                bootstrap_iterations=50,
            )

        run = session.query(ScanRun).one()
        progress = session.query(ScanProgress).one()
        assert run.status == "failed"
        assert progress.stage == "avs_failed"
        assert session.query(AVSComputation).count() == 0
        assert session.query(ScanProvenance).count() == 0
        assert session.query(ScanStep).filter_by(step_id="compute_avs", event="failed").count() == 1
    finally:
        session.close()
        engine.dispose()


def test_avs_marks_scan_failed_when_no_classified_samples_are_available(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_ready_for_avs(session, tmp_path=tmp_path)
        session.query(Classification).delete()
        session.query(Sample).delete()
        session.commit()

        with pytest.raises(AVSComputationError, match="No classified samples"):
            compute_scan_avs(
                session,
                scan_run_id=SCAN_RUN_ID,
                actor_id="system",
                bootstrap_iterations=50,
            )

        run = session.query(ScanRun).one()
        progress = session.query(ScanProgress).one()
        assert run.status == "failed"
        assert progress.stage == "avs_failed"
        assert session.query(ScanStep).filter_by(step_id="compute_avs", event="failed").count() == 1
    finally:
        session.close()
        engine.dispose()


def test_avs_existing_projection_without_success_step_is_not_mutated(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_ready_for_avs(session, tmp_path=tmp_path)
        compute_scan_avs(
            session,
            scan_run_id=SCAN_RUN_ID,
            actor_id="system",
            bootstrap_iterations=50,
        )
        session.commit()
        original = session.query(AVSComputation).one().avs_value
        session.query(ScanStep).filter_by(step_id="compute_avs", event="succeeded").delete()
        session.commit()

        with pytest.raises(AVSComputationError, match="manual repair required"):
            compute_scan_avs(
                session,
                scan_run_id=SCAN_RUN_ID,
                actor_id="system",
                bootstrap_iterations=50,
            )

        assert session.query(AVSComputation).count() == 1
        assert session.query(AVSComputation).one().avs_value == original
        run = session.query(ScanRun).one()
        assert run.status == "failed"
        assert session.query(ScanStep).filter_by(step_id="compute_avs", event="failed").count() == 1
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("failed_indexes", [(4,), (3, 4)])
def test_avs_partial_completion_accepts_at_least_three_samples_per_cell(tmp_path, monkeypatch, failed_indexes):
    engine, Session = _sessionmaker()
    session = Session()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_ready_for_avs(session, tmp_path=tmp_path)
        for question_id in ("question-00", "question-01"):
            for sample_index in failed_indexes:
                _mark_sample_failed(session, question_id=question_id, sample_index=sample_index)
        _rewrite_raw_archive_from_samples(session)
        session.commit()

        result = compute_scan_avs(
            session,
            scan_run_id=SCAN_RUN_ID,
            actor_id="system",
            bootstrap_iterations=50,
        )
        session.commit()

        assert result.completeness == "partial_acceptable"
        run = session.query(ScanRun).one()
        progress = session.query(ScanProgress).one()
        assert run.status == "succeeded"
        assert progress.status == "succeeded"
        assert progress.stage == "avs_computed"
    finally:
        session.close()
        engine.dispose()


def test_avs_partial_completion_degrades_below_three_samples_per_cell(tmp_path, monkeypatch):
    engine, Session = _sessionmaker()
    session = Session()
    monkeypatch.setenv("AISO_STORAGE_ROOT", str(tmp_path))
    try:
        _seed_scan_ready_for_avs(session, tmp_path=tmp_path)
        for question_id in ("question-00", "question-01"):
            for sample_index in (2, 3, 4):
                _mark_sample_failed(session, question_id=question_id, sample_index=sample_index)
        _rewrite_raw_archive_from_samples(session)
        session.commit()

        result = compute_scan_avs(
            session,
            scan_run_id=SCAN_RUN_ID,
            actor_id="system",
            bootstrap_iterations=50,
        )
        session.commit()

        assert result.completeness == "partial_degraded"
        run = session.query(ScanRun).one()
        progress = session.query(ScanProgress).one()
        assert run.status == "partial"
        assert progress.status == "partial"
        assert progress.stage == "avs_computed"
    finally:
        session.close()
        engine.dispose()


def test_avs_positivity_is_not_biased_by_mention_position():
    samples = {
        ("q1", "openai"): [
            AVSSample("q1", "openai", 0, "VectorCRM appears first. Other context follows.", "R+", 1.0),
            AVSSample("q1", "openai", 1, "Other context appears first. VectorCRM appears second.", "R-", 1.0),
        ]
    }

    indices = compute_subindices(samples, target_aliases=["VectorCRM"])

    assert indices.positivity == pytest.approx(0.5)


def test_avs_alias_matching_requires_phrase_boundaries():
    aliases = normalized_aliases(["spa"])

    assert first_mention_position("The spa is open now.", aliases) == (1, 1)
    assert first_mention_position("Sparking reviews are strong.", aliases) is None


def test_wilson_interval_matches_spec_formula():
    lo, hi = wilson_interval(3, 5)
    assert lo == pytest.approx(0.2307, abs=0.0001)
    assert hi == pytest.approx(0.8824, abs=0.0001)


def _sessionmaker():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _seed_scan_ready_for_avs(session, *, tmp_path: Path, all_mentions: bool = True) -> None:
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
    session.add(Scan(id=SCAN_RUN_ID, client_id="client-1", status="running"))
    session.add(
        ScanResult(
            id="legacy-result-1",
            scan_id=SCAN_RUN_ID,
            client_id="client-1",
            provider="openai",
            group="AVS",
            total_questions=2,
            mention_count=0,
            visibility_score=0.0,
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
            stage="classification_completed",
            total_calls=10,
            completed_calls=10,
            failed_calls=0,
            per_provider={
                "openai": {"completed": 10, "failed": 0, "rate_limited": 0, "last_status": "classification_completed"},
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
    for question_id, weight in (("question-00", Decimal("2.0000")), ("question-01", Decimal("1.0000"))):
        session.add(
            QuestionBankQuestion(
                question_id=question_id,
                client_id="client-1",
                text=f"What should buyers evaluate for VectorCRM {question_id}?",
                text_hash=f"hash-{question_id}",
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
                weight_at_scan=weight,
                state_at_scan="FROZEN",
            )
        )

    raw_archive: list[dict] = []
    for sample in _seed_samples(all_mentions=all_mentions):
        sample_id = f"sample-{sample.question_id}-{sample.sample_index}"
        raw_hash = hashlib.sha256(sample.text.encode("utf-8")).digest()
        session.add(
            ExecutionSample(
                scan_run_id=SCAN_RUN_ID,
                question_id=sample.question_id,
                provider=sample.provider,
                sample_index=sample.sample_index,
                planned_provider_model="gpt-test",
                provider_model="gpt-test-actual",
                temperature=Decimal("0.700"),
                top_p=Decimal("1.000"),
                seed=sample.sample_index,
                request_payload_hash=b"r" * 32,
                raw_response={"metadata": {}},
                raw_response_text=sample.text,
                raw_response_hash=raw_hash,
                system_fingerprint="fp-test",
                cost_usd=Decimal("0.001000"),
                provider_idem_key=f"idem-{sample_id}",
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                response_received_at=datetime(2026, 5, 24, 12, 5, tzinfo=timezone.utc),
                latency_ms=100,
                methodology_version=METHODOLOGY_VERSION,
                cache_bust={},
            )
        )
        session.add(
            Sample(
                id=sample_id,
                scan_id=SCAN_RUN_ID,
                question_id=sample.question_id,
                provider=sample.provider,
                provider_model="gpt-test-actual",
                system_fingerprint="fp-test",
                temperature=Decimal("0.700"),
                top_p=Decimal("1.000"),
                seed=sample.sample_index,
                sample_index=sample.sample_index,
                request_payload_hash=b"r" * 32,
                raw_response_text=sample.text,
                raw_response_hash=raw_hash,
                response_received_at=datetime(2026, 5, 24, 12, 5, tzinfo=timezone.utc),
                latency_ms=100,
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                methodology_version=METHODOLOGY_VERSION,
            )
        )
        session.add(
            Classification(
                id=f"classification-{sample_id}",
                sample_id=sample_id,
                classifier_type="stance",
                classifier_version="classifier-1.0.0",
                classifier_model="claude-sonnet-4-test",
                prompt_hash=b"p" * 32,
                self_consistency_n=3,
                individual_judgments=[sample.stance_label] * 3,
                consensus_value=sample.stance_label,
                consensus_confidence=Decimal("1.0000"),
            )
        )
        raw_archive.append(
            {
                "question_id": sample.question_id,
                "provider": sample.provider,
                "sample_index": sample.sample_index,
                "raw_response_text": sample.text,
                "raw_response_hash": raw_hash.hex(),
            }
        )
    archive_path = tmp_path / "raw_response_archive.json"
    archive_bytes = json.dumps(raw_archive, sort_keys=True, separators=(",", ":")).encode("utf-8")
    archive_path.write_bytes(archive_bytes)
    session.add(
        ScanRawResponseArchive(
            id="raw-archive-1",
            scan_id=SCAN_RUN_ID,
            archive_type="provider_raw_responses",
            sample_count=len(raw_archive),
            archive_url=str(archive_path),
            archive_hash=hashlib.sha256(archive_bytes).digest(),
        )
    )


def _seed_samples(*, all_mentions: bool) -> list[AVSSample]:
    if not all_mentions:
        return [
            AVSSample(
                question_id=f"question-{index // 5:02d}",
                provider="openai",
                sample_index=index % 5,
                text="Another CRM is mentioned. It is easy.",
                stance_label="N",
                stance_confidence=1.0,
                question_weight=2.0 if index < 5 else 1.0,
            )
            for index in range(10)
        ]
    return [
        AVSSample("question-00", "openai", 0, "VectorCRM is recommended. It is easy.", "R+", 1.0, 2.0),
        AVSSample("question-00", "openai", 1, "VectorCRM is a useful option. It is easy.", "C+", 1.0, 2.0),
        AVSSample("question-00", "openai", 2, "VectorCRM is mentioned. It is easy.", "N", 1.0, 2.0),
        AVSSample("question-00", "openai", 3, "Another CRM is mentioned. It is easy.", "N", 1.0, 2.0),
        AVSSample("question-00", "openai", 4, "Another CRM is mentioned. It is easy.", "N", 1.0, 2.0),
        AVSSample("question-01", "openai", 0, "VectorCRM is not recommended. It is difficult.", "R-", 1.0, 1.0),
        AVSSample("question-01", "openai", 1, "Another CRM is mentioned. It is easy.", "N", 1.0, 1.0),
        AVSSample("question-01", "openai", 2, "Another CRM is mentioned. It is easy.", "N", 1.0, 1.0),
        AVSSample("question-01", "openai", 3, "Another CRM is mentioned. It is easy.", "N", 1.0, 1.0),
        AVSSample("question-01", "openai", 4, "Another CRM is mentioned. It is easy.", "N", 1.0, 1.0),
    ]


def _expected_samples_by_pair() -> dict[tuple[str, str], list[AVSSample]]:
    samples = _seed_samples(all_mentions=True)
    return {
        ("question-00", "openai"): samples[:5],
        ("question-01", "openai"): samples[5:],
    }


def _mark_sample_failed(session, *, question_id: str, sample_index: int) -> None:
    sample_id = f"sample-{question_id}-{sample_index}"
    session.query(Classification).filter(Classification.sample_id == sample_id).delete()
    session.query(Sample).filter(Sample.id == sample_id).delete()
    execution_sample = (
        session.query(ExecutionSample)
        .filter(
            ExecutionSample.scan_run_id == SCAN_RUN_ID,
            ExecutionSample.question_id == question_id,
            ExecutionSample.provider == "openai",
            ExecutionSample.sample_index == sample_index,
        )
        .one()
    )
    execution_sample.raw_response = None
    execution_sample.raw_response_text = None
    execution_sample.raw_response_hash = None
    execution_sample.failure_reason = "provider_timeout"


def _rewrite_raw_archive_from_samples(session) -> None:
    archive = session.query(ScanRawResponseArchive).one()
    samples = (
        session.query(Sample)
        .filter(Sample.scan_id == SCAN_RUN_ID)
        .order_by(Sample.question_id.asc(), Sample.provider.asc(), Sample.sample_index.asc())
        .all()
    )
    raw_archive = [
        {
            "question_id": sample.question_id,
            "provider": sample.provider,
            "sample_index": sample.sample_index,
            "raw_response_text": sample.raw_response_text,
            "raw_response_hash": sample.raw_response_hash.hex(),
        }
        for sample in samples
    ]
    archive_path = Path(archive.archive_url)
    archive_bytes = json.dumps(raw_archive, sort_keys=True, separators=(",", ":")).encode("utf-8")
    archive_path.write_bytes(archive_bytes)
    archive.sample_count = len(raw_archive)
    archive.archive_hash = hashlib.sha256(archive_bytes).digest()

    progress = session.query(ScanProgress).one()
    failed_calls = session.query(ExecutionSample).filter(ExecutionSample.failure_reason.is_not(None)).count()
    completed_calls = session.query(ExecutionSample).filter(ExecutionSample.raw_response_hash.is_not(None)).count()
    progress.completed_calls = completed_calls
    progress.failed_calls = failed_calls
