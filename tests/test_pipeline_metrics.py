import asyncio
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import (
    AVSComputation,
    Action,
    Base,
    Classification,
    Client,
    MethodologyVersionSet,
    QuestionBankQuestion,
    QuestionBankVersion,
    Sample,
    Scan,
    ScanCitation,
    ScanManifest,
    ScanResult,
    ScanRun,
    User,
)
from api.routes.pipeline import _db_backed_gap_report, get_client_metrics, get_scan_metrics_timeline, get_scan, list_scans


class PipelineMetricsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_competitor_scores_are_scoped_to_each_provider(self):
        session = self.Session()
        try:
            session.add(User(id="user-1", email="founder@example.com"))
            session.add(
                Client(
                    id="client-1",
                    user_id="user-1",
                    name="Pempsa",
                    url="https://pempsa.example",
                    competitor_names=json.dumps(["Bella Boutique Spa", "Christine's Day Spa"]),
                )
            )
            session.add(
                Scan(
                    id="scan-1",
                    client_id="client-1",
                    status="complete",
                    providers=json.dumps(["perplexity", "openai"]),
                    groups=json.dumps(["G2"]),
                )
            )
            session.add_all(
                [
                    ScanResult(
                        id="result-1",
                        scan_id="scan-1",
                        client_id="client-1",
                        provider="perplexity",
                        group="G2",
                        total_questions=12,
                        mention_count=9,
                        competitor_data=json.dumps(
                            {
                                "Bella Boutique Spa": 0,
                                "Christine's Day Spa": 0,
                            }
                        ),
                    ),
                    ScanResult(
                        id="result-2",
                        scan_id="scan-1",
                        client_id="client-1",
                        provider="openai",
                        group="G2",
                        total_questions=4,
                        mention_count=1,
                        competitor_data=json.dumps(
                            {
                                "Bella Boutique Spa": 2,
                                "Christine's Day Spa": 0,
                            }
                        ),
                    ),
                    ScanResult(
                        id="manual-result",
                        scan_id="scan-1",
                        client_id="client-1",
                        provider="openai",
                        group="MANUAL",
                        total_questions=50,
                        mention_count=0,
                        competitor_data=json.dumps({"Bella Boutique Spa": 50}),
                    ),
                ]
            )
            session.commit()

            metrics = asyncio.run(
                get_client_metrics(
                    "client-1",
                    scan_id=None,
                    db=session,
                    user_id="user-1",
                )
            )

            provider_ids = {item.id for item in metrics.provider_metrics}
            self.assertEqual(provider_ids, {"openai", "perplexity"})

            you = next(item for item in metrics.competitors if item.is_you)
            bella = next(item for item in metrics.competitors if item.name == "Bella Boutique Spa")

            self.assertEqual(you.provider_scores["perplexity"], 75.0)
            self.assertEqual(you.provider_scores["openai"], 25.0)
            self.assertEqual(bella.provider_scores["perplexity"], 0.0)
            self.assertEqual(bella.provider_scores["openai"], 50.0)
            self.assertEqual(metrics.total_questions, 16)
            self.assertFalse(any(item.id == "MANUAL" for item in metrics.group_metrics))
        finally:
            session.close()

    def test_metrics_prefer_phase13_avs_projection_without_legacy_scan_results(self):
        session = self.Session()
        try:
            self._seed_phase13_completed_scan(session)
            session.commit()

            metrics = asyncio.run(
                get_client_metrics(
                    "client-1",
                    scan_id=None,
                    db=session,
                    user_id="user-1",
                )
            )

            self.assertEqual(metrics.scan_id, "scan-run-1")
            self.assertEqual(metrics.status, "complete")
            self.assertEqual(metrics.overall_score, 68.5)
            self.assertEqual(metrics.visibility_score, 68.5)
            self.assertEqual(metrics.total_questions, 4)
            self.assertEqual(
                {item.id: (item.mention_count, item.total_questions) for item in metrics.provider_metrics},
                {"claude": (1, 2), "openai": (1, 2)},
            )
            self.assertEqual({item.id for item in metrics.group_metrics}, {"J2", "J4"})
            self.assertEqual(metrics.competitors[0].name, "Pempsa")
            self.assertTrue(metrics.competitors[0].is_you)
            self.assertEqual(metrics.competitors[0].score, 68.5)
            rival = next(item for item in metrics.competitors if item.name == "Bella Boutique Spa")
            self.assertEqual(rival.mention_count, 0)
        finally:
            session.close()

    def test_scan_list_detail_and_timeline_include_phase13_completed_runs(self):
        session = self.Session()
        try:
            self._seed_phase13_completed_scan(session)
            session.commit()

            scans = asyncio.run(list_scans("client-1", db=session, user_id="user-1"))
            self.assertEqual(len(scans), 1)
            self.assertEqual(scans[0]["id"], "scan-run-1")
            self.assertEqual(scans[0]["status"], "complete")
            self.assertEqual(scans[0]["providers"], ["openai", "claude"])

            detail = asyncio.run(get_scan("client-1", "scan-run-1", db=session, user_id="user-1"))
            self.assertEqual(detail["id"], "scan-run-1")
            self.assertEqual(detail["artifacts"], [])

            timeline = asyncio.run(
                get_scan_metrics_timeline(client_id="client-1", db=session, user_id="user-1")
            )
            self.assertEqual(len(timeline), 1)
            self.assertEqual(timeline[0].scan_id, "scan-run-1")
            self.assertEqual(timeline[0].metrics.overall_score, 68.5)
            self.assertEqual(timeline[0].metrics.mention_count, 2)
            self.assertEqual(timeline[0].metrics.gap_count, 2)
        finally:
            session.close()

    def test_db_gap_report_excludes_manual_rows(self):
        session = self.Session()
        try:
            user = User(id="user-1", email="founder@example.com")
            client = Client(
                id="client-1",
                user_id="user-1",
                name="Pempsa",
                url="https://pempsa.example",
                competitor_names=json.dumps(["Bella Boutique Spa"]),
            )
            scan = Scan(
                id="scan-1",
                client_id="client-1",
                status="complete",
                providers=json.dumps(["openai"]),
                groups=json.dumps(["G2"]),
            )
            session.add_all([user, client, scan])
            session.add_all(
                [
                    ScanResult(
                        id="templated-result",
                        scan_id="scan-1",
                        client_id="client-1",
                        provider="openai",
                        group="G2",
                        total_questions=2,
                        mention_count=1,
                        competitor_data=json.dumps({"Bella Boutique Spa": 1}),
                    ),
                    ScanResult(
                        id="manual-result",
                        scan_id="scan-1",
                        client_id="client-1",
                        provider="openai",
                        group="MANUAL",
                        total_questions=10,
                        mention_count=0,
                        competitor_data=json.dumps({"Bella Boutique Spa": 10}),
                    ),
                ]
            )
            session.add_all(
                [
                    ScanCitation(
                        id="citation-1",
                        client_id="client-1",
                        scan_id="scan-1",
                        provider="openai",
                        group="G2",
                        question="Is Pempsa worth it?",
                        answer_excerpt="Pempsa is mentioned.",
                        citation_url="https://pempsa.example",
                        source_domain="pempsa.example",
                    ),
                    ScanCitation(
                        id="manual-citation",
                        client_id="client-1",
                        scan_id="scan-1",
                        provider="openai",
                        group="MANUAL",
                        question="Manual competitor question?",
                        answer_excerpt="Bella Boutique Spa is mentioned.",
                        citation_url="https://bella.example",
                        source_domain="bella.example",
                    ),
                ]
            )
            session.commit()

            report = _db_backed_gap_report(session, client, scan)

            self.assertEqual(report["summary"]["total_provider_question_results"], 2)
            self.assertFalse(any(item["group"] == "MANUAL" for item in report["coverage"]))
            self.assertFalse(any(item["group"] == "MANUAL" for item in report["query_results"]))
        finally:
            session.close()

    def test_metrics_timeline_is_chronological_and_user_scoped(self):
        session = self.Session()
        now = datetime.now(timezone.utc)
        try:
            session.add_all(
                [
                    User(id="user-1", email="founder@example.com"),
                    User(id="user-2", email="other@example.com"),
                    Client(id="client-1", user_id="user-1", name="AISO Demo", url="https://example.com"),
                    Client(id="client-2", user_id="user-2", name="Other Demo", url="https://other.example"),
                ]
            )
            session.add_all(
                [
                    Scan(
                        id="scan-old",
                        client_id="client-1",
                        status="complete",
                        created_at=now - timedelta(days=7),
                        completed_at=now - timedelta(days=7),
                    ),
                    Scan(
                        id="scan-new",
                        client_id="client-1",
                        status="complete",
                        created_at=now,
                        completed_at=now,
                    ),
                    Scan(
                        id="scan-other-user",
                        client_id="client-2",
                        status="complete",
                        created_at=now - timedelta(days=1),
                        completed_at=now - timedelta(days=1),
                    ),
                ]
            )
            session.add_all(
                [
                    ScanResult(
                        id="old-result",
                        scan_id="scan-old",
                        client_id="client-1",
                        provider="openai",
                        group="G2",
                        total_questions=10,
                        mention_count=4,
                    ),
                    ScanResult(
                        id="new-result",
                        scan_id="scan-new",
                        client_id="client-1",
                        provider="openai",
                        group="G2",
                        total_questions=10,
                        mention_count=7,
                    ),
                    ScanResult(
                        id="manual-result",
                        scan_id="scan-new",
                        client_id="client-1",
                        provider="openai",
                        group="MANUAL",
                        total_questions=10,
                        mention_count=0,
                    ),
                    ScanResult(
                        id="other-user-result",
                        scan_id="scan-other-user",
                        client_id="client-2",
                        provider="openai",
                        group="G2",
                        total_questions=10,
                        mention_count=10,
                    ),
                ]
            )
            session.add_all(
                [
                    Action(
                        id="open-action",
                        client_id="client-1",
                        scan_id="scan-new",
                        title="Update service page",
                        status="open",
                    ),
                    Action(
                        id="done-action",
                        client_id="client-1",
                        scan_id="scan-new",
                        title="Add source citations",
                        status="done",
                    ),
                    Action(
                        id="other-user-action",
                        client_id="client-2",
                        scan_id="scan-other-user",
                        title="Private action",
                        status="done",
                    ),
                ]
            )
            session.commit()

            points = asyncio.run(get_scan_metrics_timeline(client_id=None, db=session, user_id="user-1"))

            self.assertEqual([point.scan_id for point in points], ["scan-old", "scan-new"])
            self.assertEqual(points[0].metrics.overall_score, 40.0)
            self.assertEqual(points[1].metrics.overall_score, 70.0)
            self.assertEqual(points[1].metrics.gap_count, 3)
            self.assertEqual(points[1].metrics.action_count, 2)
            self.assertEqual(points[1].metrics.completed_action_count, 1)
            self.assertEqual(points[1].metrics.action_completion_rate, 50.0)
        finally:
            session.close()

    def _seed_phase13_completed_scan(self, session):
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
                name="Pempsa",
                url="https://pempsa.example",
                competitor_names=json.dumps(["Bella Boutique Spa"]),
            )
        )
        session.add(
            ScanRun(
                id="scan-run-1",
                client_id="client-1",
                idempotency_key="idem-1",
                methodology_version="AVS-1.0.0+N-sampling-1.0.0+classifier-1.0.0",
                methodology_version_set_id="mvs-1",
                status="succeeded",
                completeness="complete",
                cost_budget_usd=Decimal("12.0000"),
                cost_spent_usd=Decimal("0.004000"),
                latency_class="standard",
                providers=["openai", "claude"],
                enqueued_at=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
                started_at=datetime(2026, 5, 24, 12, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 5, 24, 12, 10, tzinfo=timezone.utc),
            )
        )
        session.add(
            AVSComputation(
                id="avs-1",
                scan_id="scan-run-1",
                methodology_version_set_id="mvs-1",
                avs_value=Decimal("68.500"),
                presence=Decimal("0.50000"),
                prominence=Decimal("0.80000"),
                positivity=Decimal("0.70000"),
                ci_lower_95=Decimal("55.000"),
                ci_upper_95=Decimal("80.000"),
                ci_method="BCa",
                bootstrap_iterations=2000,
                computed_by_git_sha="test-sha",
                is_primary=True,
            )
        )
        session.add(
            QuestionBankVersion(
                bank_version_id="bank-1",
                client_id="client-1",
                avs_version="AVS-1.0.0",
                effective_from=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
                n_core=2,
                n_tail=0,
                n_total=2,
                rotation_reason="phase12_initial_import",
            )
        )
        questions = [
            ("question-1", "J2", "What should I compare before booking Pempsa?"),
            ("question-2", "J4", "How much does a Pempsa appointment cost?"),
        ]
        for question_id, journey_stage, text in questions:
            session.add(
                QuestionBankQuestion(
                    question_id=question_id,
                    client_id="client-1",
                    text=text,
                    text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    journey_stage=journey_stage,
                    brand_frame="B",
                    locality="L0",
                    source="generated",
                )
            )
            session.add(
                ScanManifest(
                    scan_id="scan-run-1",
                    question_id=question_id,
                    bank_version_id="bank-1",
                    weight_at_scan=Decimal("1.0000"),
                    state_at_scan="FROZEN",
                )
            )
        samples = [
            ("sample-1", "question-1", "openai", 0, "Pempsa is a strong choice for spa bookings.", "R+"),
            ("sample-2", "question-1", "openai", 1, "A different spa may be easier to book.", "N"),
            ("sample-3", "question-2", "claude", 0, "Pempsa pricing depends on the service.", "C+"),
            ("sample-4", "question-2", "claude", 1, "Most appointments vary by service.", "N"),
        ]
        for sample_id, question_id, provider, sample_index, response_text, stance in samples:
            raw_hash = hashlib.sha256(response_text.encode("utf-8")).digest()
            session.add(
                Sample(
                    id=sample_id,
                    scan_id="scan-run-1",
                    question_id=question_id,
                    provider=provider,
                    provider_model=f"{provider}-test",
                    temperature=Decimal("0.700"),
                    top_p=Decimal("1.000"),
                    seed=sample_index,
                    sample_index=sample_index,
                    request_payload_hash=b"r" * 32,
                    raw_response_text=response_text,
                    raw_response_hash=raw_hash,
                    response_received_at=datetime(2026, 5, 24, 12, 5, tzinfo=timezone.utc),
                    methodology_version="AVS-1.0.0+N-sampling-1.0.0+classifier-1.0.0",
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
                    individual_judgments=[stance] * 3,
                    consensus_value=stance,
                    consensus_confidence=Decimal("1.0000"),
                )
            )


if __name__ == "__main__":
    unittest.main()
