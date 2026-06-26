import asyncio
import csv
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.audit_log import verify_audit_chain
from api.adapters import scan_execution
from api.auth import get_current_user_id
from api.database import (
    AVSComputation,
    AuditEvent,
    Base,
    BusinessProfile,
    Classification,
    Client,
    MethodologyVersionSet,
    QuestionBankQuestion,
    QuestionCandidate,
    QuestionScore,
    Sample,
    Scan,
    ScanArtifact,
    ScanManifest,
    ScanProgress,
    ScanMetric,
    ScanProvenance,
    ScanRun,
    ScanStep,
    User,
    get_db,
)
from api.domain.ports import ProviderResponse, ScanEnqueueResult, ScanHandle
from api.domain.avs import AVSSample, avs_from_subindices, compute_avs, compute_subindices
from api.domain.question_generation import BRAND_FRAMES, INTENT_CLASSES, JOURNEY_STAGES, question_text_hash
from api.main import app
from api.question_gen.export import QUESTION_CSV_COLUMNS
from api.routes import onboarding as onboarding_routes
from api.routes import scan_runs as scan_run_routes
from api.storage import OneDriveUploadResult, materialize_artifact_file


ACCEPTANCE_PROVIDERS = ["openai", "claude", "perplexity", "gemini"]
EXPECTED_SELECTED_QUESTIONS = 50
EXPECTED_SAMPLES_PER_CELL = 5
EXPECTED_SAMPLE_COUNT = EXPECTED_SELECTED_QUESTIONS * len(ACCEPTANCE_PROVIDERS) * EXPECTED_SAMPLES_PER_CELL


class RecordingPhase12Executor:
    provider = "procrastinate_test"

    def __init__(self):
        self.calls = []

    def enqueue(self, *, scan_id: str, client_id: str) -> ScanEnqueueResult:
        self.calls.append({"scan_id": scan_id, "client_id": client_id})
        return ScanEnqueueResult(enqueued=True, provider=self.provider, job_id="phase12-job")


class RecordingPhase13Executor:
    def __init__(self):
        self.calls = []

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
        self.calls.append(
            {
                "scan_run_id": str(scan_run_id),
                "idempotency_key": idempotency_key,
                "client_id": str(client_id),
                "methodology_version": methodology_version,
                "cost_budget_usd": cost_budget_usd,
                "priority": priority,
            }
        )
        return ScanHandle(
            scan_run_id=UUID(str(scan_run_id)),
            idempotency_key=idempotency_key,
            enqueued_at=datetime.now(timezone.utc),
            methodology_version=methodology_version,
        )

    async def status(self, scan_run_id):
        raise NotImplementedError

    async def cancel(self, scan_run_id, reason: str) -> None:
        raise NotImplementedError


class BrandMentionProvider:
    def __init__(self, provider: str):
        self.provider = provider
        self.calls = []

    async def complete(
        self,
        *,
        prompt: str,
        seed: int | None,
        temperature: float,
        top_p: float,
        idempotency_key: str,
    ) -> ProviderResponse:
        use_case_index = _use_case_index(prompt)
        response_text = _fixture_provider_response(use_case_index)
        self.calls.append(
            {
                "idempotency_key": idempotency_key,
                "seed": seed,
                "use_case_index": use_case_index,
                "profile": _fixture_profile_name(use_case_index),
            }
        )
        return ProviderResponse(
            text=response_text,
            provider=self.provider,
            model=f"{self.provider}-test-model",
            raw_metadata={"safe": True},
            cost_usd=0.0001,
            input_tokens=10,
            output_tokens=15,
            total_tokens=25,
            latency_ms=42,
            response_received_at=datetime(2026, 5, 24, 12, 5, tzinfo=timezone.utc),
        )


class ConsistentClassifierJudge:
    def __init__(self):
        self.calls = []

    async def complete(
        self,
        *,
        prompt: str,
        seed: int | None,
        temperature: float,
        top_p: float,
        idempotency_key: str,
    ) -> ProviderResponse:
        label = _fixture_stance_label(prompt, idempotency_key=idempotency_key)
        self.calls.append({"idempotency_key": idempotency_key, "seed": seed, "label": label})
        return ProviderResponse(
            text=json.dumps({"label": label, "rationale": f"Fixture stance {label} for deterministic acceptance."}),
            provider="claude",
            model="claude-sonnet-4-test",
            cost_usd=0.0001,
            input_tokens=12,
            output_tokens=8,
            total_tokens=20,
        )


def test_phase_13_12_end_to_end_acceptance_from_selected_questions_to_dashboard(monkeypatch):
    # Run against real Postgres (FK-enforced, prod-faithful) when TEST_DATABASE_URL
    # is set; otherwise the legacy in-memory SQLite path. SQLite does not enforce
    # foreign keys, which is exactly why prod-only integrity bugs slipped through.
    _test_db_url = os.environ.get("TEST_DATABASE_URL")
    if _test_db_url:
        engine = create_engine(_test_db_url)
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    storage_dir = tempfile.TemporaryDirectory()
    uploaded_files: dict[str, bytes] = {}
    phase12_executor = RecordingPhase12Executor()
    phase13_executor = RecordingPhase13Executor()
    providers = {provider_name: BrandMentionProvider(provider_name) for provider_name in ACCEPTANCE_PROVIDERS}
    classifier = ConsistentClassifierJudge()

    def fake_onedrive_upload(local_path, remote_path):
        storage_path = f"onedrive://drive-test/item-{len(uploaded_files) + 1}"
        uploaded_files[storage_path] = local_path.read_bytes()
        return OneDriveUploadResult(
            drive_id="drive-test",
            item_id=f"item-{len(uploaded_files)}",
            remote_path=remote_path,
            web_url="https://onedrive.example/private",
        )

    def fake_onedrive_download(storage_path: str) -> bytes:
        return uploaded_files[storage_path]

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    env_patch = patch.dict(
        "os.environ",
        {
            "AISO_SCAN_ENGINE": "phase13",
            "AISO_STORAGE_BACKEND": "onedrive",
            "AISO_ONEDRIVE_BASE_PATH": "/AISO",
            "AISO_STORAGE_ROOT": storage_dir.name,
        },
    )
    upload_patch = patch("api.storage.upload_file_to_onedrive", side_effect=fake_onedrive_upload)
    download_patch = patch("api.storage.download_onedrive_artifact", side_effect=fake_onedrive_download)
    env_patch.start()
    upload_patch.start()
    download_patch.start()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    app.dependency_overrides[onboarding_routes.get_scan_executor] = lambda: phase12_executor
    app.dependency_overrides[scan_run_routes.get_scan_executor] = lambda: phase13_executor
    monkeypatch.setattr(scan_execution, "SessionLocal", Session)
    monkeypatch.setattr(scan_execution, "default_provider_clients", lambda: providers)
    monkeypatch.setattr(scan_execution, "default_classifier_judge", lambda: classifier)

    try:
        seed = Session()
        try:
            _seed_phase12_and_methodology_fixture(seed)
            seed.commit()
        finally:
            seed.close()

        client = TestClient(app, base_url="http://localhost")
        selection_response = client.post("/api/v1/onboarding/client-1/select-questions", json={"target_n": 50})
        assert selection_response.status_code == 200
        selection = selection_response.json()
        scan_id = selection["scan_id"]
        assert selection["selected_count"] == 50
        assert selection["scan_status"] == "ready"
        assert selection["question_csv_storage_backend"] == "onedrive"
        assert selection["question_csv_columns"] == QUESTION_CSV_COLUMNS
        assert phase12_executor.calls == [{"scan_id": scan_id, "client_id": "client-1"}]

        kickoff_response = client.post(
            "/api/v1/clients/client-1/scan-runs",
            headers={"Idempotency-Key": "11111111-1111-4111-8111-111111111111"},
            json={
                "source_scan_id": scan_id,
                "providers": ACCEPTANCE_PROVIDERS,
                "cost_budget_usd": "5.0000",
                "latency_class": "standard",
            },
        )
        assert kickoff_response.status_code == 201
        kickoff = kickoff_response.json()
        assert kickoff["scan_run_id"] == scan_id
        assert kickoff["question_count"] == EXPECTED_SELECTED_QUESTIONS
        assert kickoff["total_calls"] == EXPECTED_SAMPLE_COUNT
        assert len(phase13_executor.calls) == 1

        asyncio.run(
            scan_execution.scan_orchestrator_task(
                scan_run_id=scan_id,
                idempotency_key=kickoff["idempotency_key"],
                methodology_version=kickoff["methodology_version"],
                cost_budget_usd=kickoff["cost_budget_usd"],
            )
        )

        dashboard_response = client.get(f"/api/v1/scan-runs/{scan_id}/dashboard-projection")
        assert dashboard_response.status_code == 200
        dashboard_projection = dashboard_response.json()
        assert dashboard_projection["status"] == "succeeded"
        assert dashboard_projection["stage"] == "published"
        assert dashboard_projection["visibility_score"] == round(dashboard_projection["avs"], 2)
        assert dashboard_projection["provenance_hash"]
        assert "cai" not in dashboard_projection

        metrics_response = client.get("/api/v1/clients/client-1/metrics")
        assert metrics_response.status_code == 200
        metrics = metrics_response.json()
        assert metrics["scan_id"] == scan_id
        assert metrics["status"] == "complete"
        assert metrics["overall_score"] == metrics["visibility_score"]
        assert metrics["overall_score"] > 0

        scans_response = client.get("/api/v1/clients/client-1/scans")
        assert scans_response.status_code == 200
        scans = scans_response.json()
        assert scans[0]["id"] == scan_id
        assert scans[0]["status"] == "complete"

        timeline_response = client.get("/api/v1/scans/metrics/timeline?client_id=client-1")
        assert timeline_response.status_code == 200
        timeline = timeline_response.json()
        assert [point["scan_id"] for point in timeline] == [scan_id]
        assert timeline[0]["metrics"]["overall_score"] == metrics["overall_score"]

        db = Session()
        try:
            run = db.query(ScanRun).filter_by(id=scan_id).one()
            progress = db.query(ScanProgress).filter_by(scan_run_id=scan_id).one()
            legacy_scan = db.query(Scan).filter_by(id=scan_id).one()
            artifact = db.query(ScanArtifact).filter_by(scan_id=scan_id, artifact_type="selected_questions_csv").one()
            with materialize_artifact_file(artifact) as csv_path:
                with csv_path.open(newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    rows = list(reader)
            assert reader.fieldnames == QUESTION_CSV_COLUMNS
            assert len(rows) == EXPECTED_SELECTED_QUESTIONS
            assert run.status == "succeeded"
            assert progress.stage == "published"
            assert progress.completed_calls == EXPECTED_SAMPLE_COUNT
            assert legacy_scan.status == "complete"
            assert sum(len(provider.calls) for provider in providers.values()) == EXPECTED_SAMPLE_COUNT
            assert {name: len(provider.calls) for name, provider in providers.items()} == {
                name: EXPECTED_SELECTED_QUESTIONS * EXPECTED_SAMPLES_PER_CELL
                for name in ACCEPTANCE_PROVIDERS
            }
            assert len(classifier.calls) == EXPECTED_SAMPLE_COUNT * 3
            assert db.query(Sample).filter_by(scan_id=scan_id).count() == EXPECTED_SAMPLE_COUNT
            assert db.query(Classification).filter_by(classifier_type="stance").count() == EXPECTED_SAMPLE_COUNT
            assert db.query(Classification).filter_by(classifier_type="source").count() == EXPECTED_SAMPLE_COUNT
            assert db.query(ScanProvenance).filter_by(scan_id=scan_id).count() == 1
            provenance = db.query(ScanProvenance).filter_by(scan_id=scan_id).one()
            assert provenance.sample_count == EXPECTED_SAMPLE_COUNT
            computation = db.query(AVSComputation).filter_by(scan_id=scan_id, is_primary=True).one()
            expected_avs = _expected_avs_from_persisted_samples(db, scan_id=scan_id)
            assert float(computation.presence) == pytest.approx(expected_avs["presence"], rel=1e-9, abs=1e-9)
            assert float(computation.prominence) == pytest.approx(expected_avs["prominence"], rel=1e-9, abs=1e-9)
            assert float(computation.positivity) == pytest.approx(expected_avs["positivity"], rel=1e-9, abs=1e-9)
            assert float(computation.avs_value) == pytest.approx(expected_avs["avs_value"], rel=1e-9, abs=1e-9)
            assert float(computation.avs_value) == pytest.approx(
                round(
                    100
                    * (
                        float(computation.presence)
                        * float(computation.prominence)
                        * float(computation.positivity)
                    )
                    ** (1 / 3),
                    3,
                ),
                rel=1e-9,
                abs=1e-9,
            )
            assert 0 < float(computation.avs_value) < 100
            assert 0 < float(computation.presence) < 1
            assert 0 < float(computation.prominence) < 1
            assert 0 < float(computation.positivity) < 1
            assert not math.isclose(float(computation.presence), 1.0)
            assert not math.isclose(float(computation.prominence), 1.0)
            assert not math.isclose(float(computation.positivity), 1.0)
            assert expected_avs["avs_value"] == pytest.approx(
                round(
                    100
                    * (
                        expected_avs["presence"]
                        * expected_avs["prominence"]
                        * expected_avs["positivity"]
                    )
                    ** (1 / 3),
                    3,
                ),
                rel=1e-9,
                abs=1e-9,
            )
            assert float(computation.avs_value) == pytest.approx(
                100
                * (
                    float(computation.presence)
                    * float(computation.prominence)
                    * float(computation.positivity)
                )
                ** (1 / 3),
                rel=0,
                abs=0.001,
            )
            assert computation.ci_method in {"BCa", "percentile-fallback"}
            assert 0 <= float(computation.ci_lower_95) <= float(computation.avs_value)
            assert float(computation.avs_value) <= float(computation.ci_upper_95) <= 100
            assert math.isfinite(float(computation.avs_value))
            assert db.query(ScanStep).filter_by(scan_run_id=scan_id, step_id="publish_scan", event="succeeded").count() == 1
            assert db.query(ScanStep).filter_by(scan_run_id=scan_id, step_id="compute_cai").count() == 0
            # Dashboard projection materialized before publish (Phase 1).
            assert db.query(ScanStep).filter_by(
                scan_run_id=scan_id, step_id="materialize_dashboard_projection", event="succeeded"
            ).count() == 1
            assert db.query(ScanMetric).filter_by(scan_id=scan_id, scope_type="overall").count() == 1
            audit_actions = [row.action for row in db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()]
            assert "scan_run.created" in audit_actions
            assert "scan_run.enqueued" in audit_actions
            assert "scan_run.orchestrator_started" in audit_actions
            assert "scan_run.provider_calls_completed" in audit_actions
            assert "scan_run.samples_classified" in audit_actions
            assert "scan_run.avs_computed" in audit_actions
            assert "scan.published" in audit_actions
            assert verify_audit_chain(db, hmac_keys={1: b"aiso-local-dev-audit-key"}) == []
            _assert_fixture_variation_reached_persistence(db, scan_id=scan_id)
            _assert_integrated_zero_mention_question(db, scan_id=scan_id)
            _assert_zero_mention_avs_is_defined()
            counts_before_replay = _phase13_row_counts(db, scan_id=scan_id)
            provider_calls_before_replay = {name: len(provider.calls) for name, provider in providers.items()}
            classifier_calls_before_replay = len(classifier.calls)
        finally:
            db.close()

        asyncio.run(
            scan_execution.scan_orchestrator_task(
                scan_run_id=scan_id,
                idempotency_key=kickoff["idempotency_key"],
                methodology_version=kickoff["methodology_version"],
                cost_budget_usd=kickoff["cost_budget_usd"],
            )
        )
        replay_db = Session()
        try:
            assert _phase13_row_counts(replay_db, scan_id=scan_id) == counts_before_replay
            assert {name: len(provider.calls) for name, provider in providers.items()} == provider_calls_before_replay
            assert len(classifier.calls) == classifier_calls_before_replay
        finally:
            replay_db.close()
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(onboarding_routes.get_scan_executor, None)
        app.dependency_overrides.pop(scan_run_routes.get_scan_executor, None)
        download_patch.stop()
        upload_patch.stop()
        env_patch.stop()
        storage_dir.cleanup()
        engine.dispose()


def _seed_phase12_and_methodology_fixture(session) -> None:
    session.add(User(id="user-1", email="founder@example.com"))
    session.add(Client(id="client-1", user_id="user-1", name="VectorCRM", url="https://vector.example"))
    session.flush()  # client must exist before business_profile/candidates FK to it (prod creates it in an earlier txn)
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
        BusinessProfile(
            client_id="client-1",
            vertical="b2b_saas",
            objective="preference",
            category="sales CRM",
            icp={"firmographics": {"industry": "B2B SaaS", "employee_band": "51-200"}},
            geographic_scope={"countries": ["US"]},
            competitors=["HubSpot", "Salesforce", "Pipedrive"],
            personas={"primary": "VP Sales", "economic_buyer": "CRO"},
            crawl_artifacts={"auto_extracted": {"brand_name": "VectorCRM"}},
            floor_met=True,
        )
    )
    scored_at = datetime.now(timezone.utc)
    for index in range(150):
        stage = JOURNEY_STAGES[index % len(JOURNEY_STAGES)]
        frame = BRAND_FRAMES[(index // len(JOURNEY_STAGES)) % len(BRAND_FRAMES)]
        intent = INTENT_CLASSES[(index // (len(JOURNEY_STAGES) * len(BRAND_FRAMES))) % len(INTENT_CLASSES)]
        persona = "VP Sales" if index % 2 == 0 else "CRO"
        question = (
            f"what should {persona} evaluate for VectorCRM use case {index} "
            f"at {stage} with {frame} and {intent} intent?"
        )
        session.add(
            QuestionCandidate(
                id=f"candidate-{index}",
                client_id="client-1",
                text=question,
                text_hash=question_text_hash(question),
                journey_stage=stage,
                brand_frame=frame,
                intent_class=intent,
                persona=persona,
                locality="L0",
                rationale="Phase 13 end-to-end acceptance fixture.",
                realism_score=Decimal("0.900"),
                selected=False,
                generator_version="test-generator-v1",
                realism_filter_version="test-realism-v1",
            )
        )
        score = Decimal("0.990") - Decimal(index % 10) / Decimal("10000")
        if index % 10 not in {0, 1, 2, 3, 4}:
            score = Decimal("0.930") - Decimal(index % 20) / Decimal("1000")
        session.add(
            QuestionScore(
                question_id=f"candidate-{index}",
                scored_at=scored_at,
                d1_buyer_plausibility=Decimal("0.900"),
                d2_commercial_proximity=Decimal("0.900"),
                d3_cognitive_answerability=Decimal("0.900"),
                d4_diagnostic_power=Decimal("0.900"),
                d5_statistical_identifiability=Decimal("0.900"),
                weighted_score=score,
                rationale="Phase 13 end-to-end acceptance score.",
                scorer_version="test-scorer-v1",
            )
        )


def _expected_avs_from_persisted_samples(db, *, scan_id: str) -> dict[str, float]:
    rows = (
        db.query(Sample, Classification, ScanManifest)
        .join(
            Classification,
            (Classification.sample_id == Sample.id)
            & (Classification.classifier_type == "stance"),
        )
        .join(
            ScanManifest,
            (ScanManifest.scan_id == Sample.scan_id)
            & (ScanManifest.question_id == Sample.question_id),
        )
        .filter(Sample.scan_id == scan_id)
        .order_by(Sample.question_id.asc(), Sample.provider.asc(), Sample.sample_index.asc())
        .all()
    )
    samples_by_pair: dict[tuple[str, str], list[AVSSample]] = {}
    for sample, classification, manifest in rows:
        pair = (sample.question_id, sample.provider)
        samples_by_pair.setdefault(pair, []).append(
            AVSSample(
                question_id=sample.question_id,
                provider=sample.provider,
                sample_index=sample.sample_index,
                text=sample.raw_response_text,
                stance_label=classification.consensus_value,
                stance_confidence=float(classification.consensus_confidence),
                question_weight=float(manifest.weight_at_scan),
            )
        )

    subindices = compute_subindices(samples_by_pair, target_aliases=["VectorCRM", "vector"])
    return {
        "presence": round(subindices.presence, 5),
        "prominence": round(subindices.prominence, 5),
        "positivity": round(subindices.positivity, 5),
        "avs_value": round(avs_from_subindices(subindices), 3),
    }


def _use_case_index(text: str) -> int:
    match = re.search(r"use case (\d+)", text)
    if not match:
        return -1
    return int(match.group(1))


def _fixture_profile_name(use_case_index: int) -> str:
    profile = use_case_index % 10
    if profile == 0:
        return "zero_mention"
    if profile == 1:
        return "deep_prominence"
    if profile == 2:
        return "neutral_comparative"
    if profile == 3:
        return "negative"
    if profile == 4:
        return "judge_disagreement"
    return "positive_shallow"


def _fixture_provider_response(use_case_index: int) -> str:
    profile = _fixture_profile_name(use_case_index)
    if profile == "zero_mention":
        return (
            "NO_MENTION_ZERO The buyer should compare implementation quality, support speed, "
            "reporting depth, and pricing clarity before choosing a CRM platform."
        )
    if profile == "deep_prominence":
        return (
            "POSITIVE_DEEP The evaluation should begin with integrations, migration support, "
            "admin controls, and reporting needs. After those checks, VectorCRM can be a strong "
            "fit when the sales team wants guided pipeline adoption."
        )
    if profile == "neutral_comparative":
        return (
            "NEUTRAL_COMPARATIVE VectorCRM may fit teams that value guided adoption, while other "
            "CRM tools may be stronger for teams that need broad marketplace integrations."
        )
    if profile == "negative":
        return (
            "NEGATIVE_STANCE VectorCRM is mentioned, but this buyer should be cautious because "
            "the fixture indicates weaker enterprise customization than some alternatives."
        )
    if profile == "judge_disagreement":
        return (
            "DISAGREE_STANCE VectorCRM is a credible option, though the answer frames the choice "
            "as somewhat comparative instead of an unqualified recommendation."
        )
    return "POSITIVE_SHALLOW VectorCRM is a strong option for this buyer question. It is easy to evaluate."


def _fixture_stance_label(prompt: str, *, idempotency_key: str) -> str:
    if "NO_MENTION_ZERO" in prompt:
        return "N"
    if "NEUTRAL_COMPARATIVE" in prompt:
        return "C+"
    if "NEGATIVE_STANCE" in prompt:
        return "R-"
    if "DISAGREE_STANCE" in prompt:
        judge_index = int(idempotency_key.rsplit(":", 1)[-1])
        return "C+" if judge_index == 2 else "R+"
    return "R+"


def _phase13_row_counts(db, *, scan_id: str) -> dict[str, int]:
    return {
        "samples": db.query(Sample).filter_by(scan_id=scan_id).count(),
        "stance_classifications": db.query(Classification)
        .filter_by(classifier_type="stance")
        .join(Sample, Sample.id == Classification.sample_id)
        .filter(Sample.scan_id == scan_id)
        .count(),
        "source_classifications": db.query(Classification)
        .filter_by(classifier_type="source")
        .join(Sample, Sample.id == Classification.sample_id)
        .filter(Sample.scan_id == scan_id)
        .count(),
        "avs_computations": db.query(AVSComputation).filter_by(scan_id=scan_id).count(),
    }


def _assert_fixture_variation_reached_persistence(db, *, scan_id: str) -> None:
    sample_texts = [row.raw_response_text for row in db.query(Sample).filter_by(scan_id=scan_id).all()]
    assert any("NO_MENTION_ZERO" in text for text in sample_texts)
    assert any("POSITIVE_DEEP" in text for text in sample_texts)
    assert any("NEUTRAL_COMPARATIVE" in text for text in sample_texts)
    assert any("NEGATIVE_STANCE" in text for text in sample_texts)
    assert any("DISAGREE_STANCE" in text for text in sample_texts)

    stance_rows = (
        db.query(Classification)
        .join(Sample, Sample.id == Classification.sample_id)
        .filter(Sample.scan_id == scan_id, Classification.classifier_type == "stance")
        .all()
    )
    labels = {row.consensus_value for row in stance_rows}
    assert {"N", "R+", "C+", "R-"}.issubset(labels)
    assert any(
        row.consensus_value == "R+" and float(row.consensus_confidence) == pytest.approx(0.75, abs=1e-9)
        for row in stance_rows
    )


def _assert_integrated_zero_mention_question(db, *, scan_id: str) -> None:
    rows = (
        db.query(Sample, Classification, QuestionBankQuestion, ScanManifest)
        .join(
            Classification,
            (Classification.sample_id == Sample.id)
            & (Classification.classifier_type == "stance"),
        )
        .join(QuestionBankQuestion, QuestionBankQuestion.question_id == Sample.question_id)
        .join(
            ScanManifest,
            (ScanManifest.scan_id == Sample.scan_id)
            & (ScanManifest.question_id == Sample.question_id),
        )
        .filter(Sample.scan_id == scan_id)
        .all()
    )
    zero_rows = [
        (sample, classification, question, manifest)
        for sample, classification, question, manifest in rows
        if _use_case_index(question.text) % 10 == 0
    ]
    assert zero_rows
    selected_zero_question_ids = {question.question_id for _, _, question, _ in zero_rows}
    assert len(zero_rows) == len(selected_zero_question_ids) * len(ACCEPTANCE_PROVIDERS) * EXPECTED_SAMPLES_PER_CELL
    assert all("VectorCRM" not in sample.raw_response_text for sample, _, _, _ in zero_rows)
    assert all(classification.consensus_value == "N" for _, classification, _, _ in zero_rows)

    samples_by_pair: dict[tuple[str, str], list[AVSSample]] = {}
    for sample, classification, _, manifest in zero_rows:
        pair = (sample.question_id, sample.provider)
        samples_by_pair.setdefault(pair, []).append(
            AVSSample(
                question_id=sample.question_id,
                provider=sample.provider,
                sample_index=sample.sample_index,
                text=sample.raw_response_text,
                stance_label=classification.consensus_value,
                stance_confidence=float(classification.consensus_confidence),
                question_weight=float(manifest.weight_at_scan),
            )
        )
    subindices = compute_subindices(samples_by_pair, target_aliases=["VectorCRM", "vector"])
    zero_avs = avs_from_subindices(subindices)
    assert subindices.presence == 0.0
    assert subindices.prominence == 0.0
    assert subindices.positivity == 0.0
    assert zero_avs == 0.0
    assert math.isfinite(zero_avs)


def _assert_zero_mention_avs_is_defined() -> None:
    zero = compute_avs(
        {
            ("question-zero", "openai"): [
                AVSSample(
                    question_id="question-zero",
                    provider="openai",
                    sample_index=index,
                    text="A different product is discussed without the target brand.",
                    stance_label="N",
                    stance_confidence=1.0,
                    question_weight=1.0,
                )
                for index in range(5)
            ]
        },
        target_aliases=["VectorCRM"],
        bootstrap_iterations=25,
    )
    assert zero.zero_mentions is True
    assert zero.avs_value == 0.0
    assert zero.presence == 0.0
    assert zero.prominence == 0.0
    assert zero.positivity == 0.0
    assert zero.ci_lower_95 == 0.0
    assert zero.ci_upper_95 == 0.0
    assert zero.ci_method == "percentile-fallback"
    assert math.isfinite(zero.avs_value)
