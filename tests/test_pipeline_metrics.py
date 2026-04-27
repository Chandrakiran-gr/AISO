import asyncio
import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base, Client, Scan, ScanResult, User
from api.routes.pipeline import get_client_metrics


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
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
