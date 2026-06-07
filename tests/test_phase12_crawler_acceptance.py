import json
import os
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.crawler.models import CrawlJob, OnboardingWorkspace
import api.crawler.models  # noqa: F401 - register crawler tables on Base
import api.crawler.worker as worker_module
from api.crawler.worker import run_crawl_job
from api.database import Base, BusinessProfile, Client, User
from api.website_ingestion import FetchResult, IngestionConfig


SEED_URL = "http://93.184.216.34"


def _now():
    return datetime.now(timezone.utc)


def _fixture_fetcher(pages_by_path, *, sitemap_paths=None):
    sitemap_paths = sitemap_paths or []

    def fetcher(url: str, config: IngestionConfig) -> FetchResult:
        path = urlparse(url).path or "/"
        if path == "/robots.txt":
            return FetchResult(url=url, final_url=url, status_code=200, content_type="text/plain", text="User-agent: *\nAllow: /\n")
        if path == "/sitemap.xml":
            locs = "".join(f"<url><loc>{SEED_URL}{item}</loc></url>" for item in sitemap_paths)
            return FetchResult(url=url, final_url=url, status_code=200, content_type="application/xml", text=f"<urlset>{locs}</urlset>")
        if path in pages_by_path:
            return FetchResult(url=url, final_url=url, status_code=200, content_type="text/html", text=pages_by_path[path])
        return FetchResult(url=url, final_url=url, status_code=404, content_type="text/html", text="<html><body><h1>Not found</h1></body></html>")

    return fetcher


class Phase12CrawlerAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._db_file = tempfile.NamedTemporaryFile(prefix="aiso_phase12_crawler_", suffix=".db", delete=False)
        cls._db_file.close()
        cls._engine = create_engine(f"sqlite:///{cls._db_file.name}", connect_args={"check_same_thread": False})
        cls._SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls._engine)
        Base.metadata.create_all(bind=cls._engine)
        cls._original_session_local = worker_module.SessionLocal
        worker_module.SessionLocal = cls._SessionLocal

    @classmethod
    def tearDownClass(cls):
        worker_module.SessionLocal = cls._original_session_local
        cls._engine.dispose()
        try:
            os.remove(cls._db_file.name)
        except FileNotFoundError:
            pass

    def _seed_job(self, *, vertical="b2b_saas", category="Software", max_pages=8, max_depth=1):
        now = _now()
        user_id = f"user-{uuid.uuid4()}"
        client_id = f"client-{uuid.uuid4()}"
        workspace_id = f"workspace-{uuid.uuid4()}"
        job_id = f"job-{uuid.uuid4()}"
        db = self._SessionLocal()
        try:
            db.add(User(id=user_id, email=f"{user_id}@example.com", name="Fixture User", created_at=now))
            db.add(
                Client(
                    id=client_id,
                    user_id=user_id,
                    name="Fixture Company",
                    url=SEED_URL,
                    industry=category,
                    location="United States",
                    competitor_names=["Alpha", "Beta", "Gamma"],
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                BusinessProfile(
                    client_id=client_id,
                    vertical=vertical,
                    objective="awareness",
                    category=category,
                    icp={},
                    geographic_scope={},
                    competitors=["Alpha", "Beta", "Gamma"],
                    personas={},
                    crawl_artifacts={},
                    floor_met=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                OnboardingWorkspace(
                    id=workspace_id,
                    client_id=client_id,
                    website_url=SEED_URL,
                    normalized_domain="93.184.216.34",
                    allowed_domains=["93.184.216.34"],
                    consent_confirmed=True,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                CrawlJob(
                    id=job_id,
                    workspace_id=workspace_id,
                    status="queued",
                    crawl_mode="standard",
                    max_pages=max_pages,
                    max_depth=max_depth,
                    allow_playwright_fallback=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.commit()
        finally:
            db.close()
        return client_id, job_id

    def _artifact_for_client(self, client_id: str):
        db = self._SessionLocal()
        try:
            profile = db.query(BusinessProfile).filter(BusinessProfile.client_id == client_id).one()
            return profile.crawl_artifacts
        finally:
            db.close()

    def _job_status(self, job_id: str):
        db = self._SessionLocal()
        try:
            job = db.query(CrawlJob).filter(CrawlJob.id == job_id).one()
            return job.status, (job.warnings or [])
        finally:
            db.close()

    def test_b2b_saas_fixture_extracts_tier1_schema_services_and_pricing(self):
        client_id, job_id = self._seed_job(category="AI SEO software", max_pages=6)
        fetcher = _fixture_fetcher(
            {
                "/": """
                  <html><head><title>AcmeAI</title>
                    <script type="application/ld+json">
                      {"@type":"Organization","name":"AcmeAI","url":"http://93.184.216.34"}
                    </script>
                  </head><body><h1>AI visibility command center</h1>
                    <a href="/services">Services</a><a href="/pricing">Pricing</a>
                  </body></html>
                """,
                "/services": """
                  <html><body><h1>AI Search Monitoring</h1>
                    <script type="application/ld+json">
                      {"@type":"Service","name":"AI Search Monitoring","description":"Track AI answer visibility."}
                    </script>
                    <p>Monitor ChatGPT, Claude, Perplexity, and Gemini answer visibility for B2B teams.</p>
                  </body></html>
                """,
                "/pricing": """
                  <html><body><h1>Growth Plan</h1>
                    <script type="application/ld+json">
                      {"@type":"Offer","name":"Growth Plan","price":"499","priceCurrency":"USD"}
                    </script>
                  </body></html>
                """,
            },
            sitemap_paths=["/services", "/pricing"],
        )

        run_crawl_job(job_id, fetch_page=fetcher)
        artifact = self._artifact_for_client(client_id)

        self.assertEqual(artifact["auto_extracted"]["brand_name"], "AcmeAI")
        self.assertIn("AI Search Monitoring", artifact["auto_extracted"]["product_service_taxonomy"])
        self.assertEqual(artifact["auto_extracted"]["pricing_tiers"][0]["price"], "499")
        self.assertIn(f"{SEED_URL}/pricing", artifact["tier1"]["attempted_urls"])
        self.assertIn("Organization", artifact["structured_data"])

    def test_local_dentist_fixture_extracts_localbusiness_nap(self):
        client_id, job_id = self._seed_job(vertical="local_services", category="Dentistry", max_pages=3)
        fetcher = _fixture_fetcher(
            {
                "/": """
                  <html><head><title>Newton Smile Studio</title>
                    <script type="application/ld+json">
                      {"@type":"LocalBusiness","name":"Newton Smile Studio","telephone":"617-555-0101",
                       "address":{"streetAddress":"12 Centre St","addressLocality":"Newton","addressRegion":"MA","postalCode":"02459"}}
                    </script>
                  </head><body><h1>Family dentist in Newton</h1><a href="/services">Services</a></body></html>
                """,
                "/services": "<html><body><h1>Dental cleanings</h1><p>Preventive dentistry and whitening services.</p></body></html>",
            }
        )

        run_crawl_job(job_id, fetch_page=fetcher)
        artifact = self._artifact_for_client(client_id)

        nap = artifact["auto_extracted"]["nap"]
        self.assertEqual(nap["name"], "Newton Smile Studio")
        self.assertEqual(nap["telephone"], "617-555-0101")
        self.assertEqual(nap["address"]["addressLocality"], "Newton")
        self.assertIn("LocalBusiness", artifact["structured_data"])

    def test_ecommerce_fixture_extracts_product_and_offer_schema(self):
        client_id, job_id = self._seed_job(vertical="ecommerce", category="Skincare", max_pages=4)
        fetcher = _fixture_fetcher(
            {
                "/": """
                  <html><head><title>GlowKit</title>
                    <script type="application/ld+json">
                      {"@type":"Product","name":"GlowKit Vitamin C Serum","description":"Brightening serum",
                       "offers":{"@type":"Offer","price":"39.00","priceCurrency":"USD","availability":"InStock"}}
                    </script>
                  </head><body><h1>GlowKit Vitamin C Serum</h1><a href="/products">Products</a></body></html>
                """,
                "/products": "<html><body><h1>Vitamin C Serum</h1><p>Clean skincare for daily brightening.</p></body></html>",
            },
            sitemap_paths=["/products"],
        )

        run_crawl_job(job_id, fetch_page=fetcher)
        artifact = self._artifact_for_client(client_id)

        self.assertIn("Product", artifact["structured_data"])
        self.assertIn("Offer", artifact["structured_data"])
        self.assertIn("GlowKit Vitamin C Serum", artifact["auto_extracted"]["product_service_taxonomy"])
        self.assertEqual(artifact["auto_extracted"]["pricing_tiers"][0]["price"], "39.00")

    def test_spa_fixture_uses_playwright_fallback_for_empty_root(self):
        client_id, job_id = self._seed_job(category="CRM software", max_pages=1)

        def static_fetch(url: str, config: IngestionConfig) -> FetchResult:
            path = urlparse(url).path or "/"
            if path == "/robots.txt":
                return FetchResult(url=url, final_url=url, status_code=404, content_type="text/plain", text="")
            if path == "/sitemap.xml":
                return FetchResult(url=url, final_url=url, status_code=404, content_type="application/xml", text="")
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                text="<html><body><div id='root'></div><script src='/app.js'></script></body></html>",
            )

        def rendered_fetch(url: str, config: IngestionConfig) -> FetchResult:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html; rendered=playwright",
                text="""
                  <html><head><title>VectorCRM</title>
                    <script type="application/ld+json">
                      {"@type":"Organization","name":"VectorCRM"}
                    </script>
                  </head><body><h1>Pipeline analytics for sales teams</h1>
                    <p>VectorCRM helps revenue teams forecast pipeline risk and coach account executives.</p>
                  </body></html>
                """,
            )

        run_crawl_job(job_id, fetch_page=static_fetch, render_page=rendered_fetch)
        artifact = self._artifact_for_client(client_id)

        self.assertEqual(artifact["playwright_invocations"], 1)
        self.assertTrue(artifact["rendered_dom"])
        self.assertEqual(artifact["auto_extracted"]["brand_name"], "VectorCRM")
        self.assertTrue(artifact["pages"][0]["rendered_dom"])

    def test_deadline_fixture_persists_partial_artifact_without_failing_job(self):
        client_id, job_id = self._seed_job(category="Operations software", max_pages=4)
        previous_timeout = os.environ.get("AISO_CRAWLER_TOTAL_TIMEOUT_SECONDS")
        os.environ["AISO_CRAWLER_TOTAL_TIMEOUT_SECONDS"] = "0.03"

        def slow_fetch(url: str, config: IngestionConfig) -> FetchResult:
            path = urlparse(url).path or "/"
            if path == "/about":
                time.sleep(0.05)
            return _fixture_fetcher(
                {
                    "/": "<html><body><h1>OpsPilot</h1><a href='/about'>About</a></body></html>",
                    "/about": "<html><body><h1>About OpsPilot</h1><p>Workflow automation for operations teams.</p></body></html>",
                },
                sitemap_paths=["/about"],
            )(url, config)

        try:
            run_crawl_job(job_id, fetch_page=slow_fetch)
        finally:
            if previous_timeout is None:
                os.environ.pop("AISO_CRAWLER_TOTAL_TIMEOUT_SECONDS", None)
            else:
                os.environ["AISO_CRAWLER_TOTAL_TIMEOUT_SECONDS"] = previous_timeout

        artifact = self._artifact_for_client(client_id)
        status, warnings = self._job_status(job_id)

        self.assertEqual(artifact["partial"], True)
        self.assertEqual(artifact["truncation_reason"], "deadline_exceeded")
        self.assertGreaterEqual(artifact["page_count"], 1)
        self.assertIn("completed", status)
        self.assertTrue(any("couldn't fully crawl" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
