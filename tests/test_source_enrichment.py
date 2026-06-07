import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import database as database_module
from api.database import Base, Client, Scan, ScanCitation, SourceProfile, User
from api.website_ingestion import FetchResult
from full_stack.source_enrichment import SourceEnrichmentConfig, enrich_source_profiles_for_scan


class SourceEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_enriches_top_source_profile_with_compact_public_signals(self):
        session = self.Session()
        try:
            session.add(User(id="user-1", email="founder@example.com", provider="google"))
            session.add(
                Client(
                    id="client-1",
                    user_id="user-1",
                    name="PemSpa",
                    url="https://pempsa.com",
                    competitor_names=["Glowbar Chestnut Hill"],
                )
            )
            session.add(Scan(id="scan-1", client_id="client-1", status="complete"))
            session.add(
                SourceProfile(
                    id="source-1",
                    client_id="client-1",
                    canonical_url="https://example.com/best-facials",
                    source_domain="example.com",
                    owner_type="third_party",
                    source_type="unknown_review_needed",
                    action_role="direct_citation_target",
                    actionability_score=7.0,
                    influence_score=8.0,
                    relevance_score=7.0,
                    metadata_json={"citation_count": 4},
                )
            )
            session.add(
                ScanCitation(
                    id="citation-1",
                    client_id="client-1",
                    scan_id="scan-1",
                    source_profile_id="source-1",
                    provider="perplexity",
                    citation_url="https://example.com/best-facials",
                    canonical_url="https://example.com/best-facials",
                    source_domain="example.com",
                    source_rank=1,
                )
            )
            session.commit()
        finally:
            session.close()

        def fake_fetch(url, config):
            self.assertEqual(url, "https://example.com/best-facials")
            self.assertEqual(config.max_pages, 1)
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                text=(
                    "<html><head><title>Best facials in Newton</title></head>"
                    "<body><h1>Best facials in Newton</h1>"
                    "<p>PemSpa and Glowbar Chestnut Hill are frequently compared.</p></body></html>"
                ),
            )

        with patch.object(database_module, "SessionLocal", self.Session):
            summary = enrich_source_profiles_for_scan(
                "scan-1",
                "client-1",
                config=SourceEnrichmentConfig(enabled=True, max_sources=1),
                fetch_page=fake_fetch,
            )

        session = self.Session()
        try:
            self.assertEqual(summary.attempted, 1)
            self.assertEqual(summary.enriched, 1)
            profile = session.query(SourceProfile).one()
            self.assertEqual(profile.fetch_status, "fetched")
            self.assertEqual(profile.source_title, "Best facials in Newton")
            self.assertEqual(profile.client_mentioned, True)
            self.assertIn("Glowbar Chestnut Hill", profile.competitors_mentioned_json)
            metadata = profile.metadata_json
            self.assertEqual(metadata["enrichment"]["source"], "static_http")
            self.assertNotIn("<html", json.dumps(metadata).lower())
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
