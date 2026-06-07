import asyncio
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base, Client, Scan, ScanArtifact, ScanCitation, ScanResult, User
from api.routes.pipeline import get_client_gap_report


class GapReportFallbackTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _seed_scan(self, session) -> None:
        session.add(User(id="user-1", email="founder@example.com", provider="credentials", is_active=True))
        session.add(
            Client(
                id="client-1",
                user_id="user-1",
                name="PemSpa Skincare & Wellness",
                url="https://pempsa.com",
                competitor_names=["Bella Boutique Spa"],
            )
        )
        session.add(Scan(id="scan-1", client_id="client-1", status="complete"))
        session.add(
            ScanResult(
                id="result-1",
                scan_id="scan-1",
                client_id="client-1",
                provider="perplexity",
                group="G4",
                total_questions=8,
                mention_count=2,
                visibility_score=25,
                competitor_data='{"Bella Boutique Spa": 3}',
            )
        )
        session.add(
            ScanCitation(
                id="citation-1",
                scan_id="scan-1",
                client_id="client-1",
                provider="perplexity",
                group="G4",
                question="how much does a chemical peel cost near Newton?",
                answer_excerpt="Bella Boutique Spa is visible for chemical peel cost searches.",
                citation_url="https://www.yelp.com/biz/bella-boutique-spa",
                citation_title="Bella Boutique Spa Reviews",
                source_domain="yelp.com",
                source_rank=1,
                canonical_url="https://yelp.com/biz/bella-boutique-spa",
                citation_origin="native_citation",
                web_search_used=True,
                source_type="directory_or_review",
                owner_type="third_party",
                action_role="listing_or_profile_target",
                actionability_score=8.5,
                confidence_score=8.0,
                classification_reason="Review directory profile",
            )
        )
        session.commit()

    def test_gap_report_falls_back_to_persisted_scan_rows_when_artifact_missing(self):
        session = self.Session()
        try:
            self._seed_scan(session)

            report = asyncio.run(
                get_client_gap_report(
                    "client-1",
                    scan_id="scan-1",
                    db=session,
                    user_id="user-1",
                )
            )

            self.assertEqual(report["report_source"], "database_fallback")
            self.assertEqual(report["summary"]["total_provider_question_results"], 8)
            self.assertEqual(report["summary"]["appeared_count"], 2)
            self.assertEqual(report["summary"]["missed_count"], 6)
            self.assertTrue(report["priority_fixes"])
            self.assertTrue(report["query_results"])
            self.assertEqual(report["source_opportunities"][0]["domain"], "yelp.com")
        finally:
            session.close()

    def test_gap_report_falls_back_when_registered_local_artifact_is_gone(self):
        session = self.Session()
        try:
            self._seed_scan(session)
            session.add(
                ScanArtifact(
                    id="artifact-1",
                    client_id="client-1",
                    scan_id="scan-1",
                    artifact_type="collect_csv",
                    file_format="csv",
                    storage_backend="local",
                    storage_path="/tmp/aiso-missing-artifact.csv",
                )
            )
            session.commit()

            report = asyncio.run(
                get_client_gap_report(
                    "client-1",
                    scan_id="scan-1",
                    db=session,
                    user_id="user-1",
                )
            )

            self.assertEqual(report["report_source"], "database_fallback")
            self.assertEqual(report["summary"]["source_opportunity_count"], 1)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
