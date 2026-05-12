import asyncio
import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base, Client, Scan, ScanCitation, ScanResult, User
from api.routes.pipeline import _db_backed_gap_report, get_client_metrics


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
                    competitors=json.dumps(["Bella Boutique Spa", "Christine's Day Spa"]),
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

    def test_db_gap_report_excludes_manual_rows(self):
        session = self.Session()
        try:
            user = User(id="user-1", email="founder@example.com")
            client = Client(
                id="client-1",
                user_id="user-1",
                name="Pempsa",
                url="https://pempsa.example",
                competitors=json.dumps(["Bella Boutique Spa"]),
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


if __name__ == "__main__":
    unittest.main()
