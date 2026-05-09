"""Tests for onboarding crawler — consent, URL utilities, policy, and API."""

import json
import unittest

from api.crawler.consent import validate_crawl_request
from api.crawler.policy import (
    classify_page_type,
    is_social_domain,
    score_url,
    should_skip_url,
)
from api.crawler.url_utils import (
    extract_domain,
    get_allowed_domains,
    is_internal_url,
    normalize_url,
)


# ═════════════════════════════════════════════════════════════════════════════
# Consent Validation Tests
# ═════════════════════════════════════════════════════════════════════════════


class ConsentValidationTests(unittest.TestCase):
    """Tests for validate_crawl_request in api.crawler.consent."""

    def test_rejects_missing_consent_flag(self):
        with self.assertRaises(ValueError) as ctx:
            validate_crawl_request("https://example.com", consent_confirmed=False)
        self.assertIn("consent", str(ctx.exception).lower())

    def test_rejects_empty_url(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("", consent_confirmed=True)

    def test_rejects_invalid_scheme(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("ftp://example.com", consent_confirmed=True)

    def test_rejects_localhost(self):
        with self.assertRaises(ValueError) as ctx:
            validate_crawl_request("http://localhost", consent_confirmed=True)
        self.assertIn("private", str(ctx.exception).lower())

    def test_rejects_loopback_ip(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("http://127.0.0.1", consent_confirmed=True)

    def test_rejects_private_ip(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("http://192.168.1.1", consent_confirmed=True)

    def test_rejects_link_local_ip(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("http://169.254.169.254", consent_confirmed=True)

    def test_rejects_internal_tld(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("http://my-service.local", consent_confirmed=True)

    def test_accepts_valid_public_url(self):
        result = validate_crawl_request("https://example.com", consent_confirmed=True)
        self.assertEqual(result["normalized_domain"], "example.com")
        self.assertIn("example.com", result["allowed_domains"])
        self.assertIn("www.example.com", result["allowed_domains"])

    def test_accepts_url_without_scheme(self):
        result = validate_crawl_request("example.com", consent_confirmed=True)
        self.assertTrue(result["safe_url"].startswith("https://"))

    def test_returns_correct_allowed_domains_for_www(self):
        result = validate_crawl_request("https://www.mysite.io", consent_confirmed=True)
        self.assertEqual(result["normalized_domain"], "mysite.io")
        self.assertIn("mysite.io", result["allowed_domains"])
        self.assertIn("www.mysite.io", result["allowed_domains"])

    def test_rejects_ipv6_localhost(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("http://[::1]", consent_confirmed=True)

    def test_rejects_aws_metadata_ip(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("http://169.254.169.254/latest/meta-data", consent_confirmed=True)

    def test_rejects_file_scheme(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("file:///etc/passwd", consent_confirmed=True)

    def test_rejects_zero_ip(self):
        with self.assertRaises(ValueError):
            validate_crawl_request("http://0.0.0.0", consent_confirmed=True)


# ═════════════════════════════════════════════════════════════════════════════
# URL Utility Tests
# ═════════════════════════════════════════════════════════════════════════════


class URLNormalizationTests(unittest.TestCase):
    """Tests for normalize_url in api.crawler.url_utils."""

    def test_removes_utm_tracking_params(self):
        url = "https://example.com/page?utm_source=google&utm_medium=cpc&key=value"
        result = normalize_url(url)
        self.assertNotIn("utm_source", result)
        self.assertNotIn("utm_medium", result)
        self.assertIn("key=value", result)

    def test_removes_fbclid(self):
        url = "https://example.com/?fbclid=abc123"
        result = normalize_url(url)
        self.assertNotIn("fbclid", result)

    def test_removes_gclid(self):
        url = "https://example.com/?gclid=xyz&real=param"
        result = normalize_url(url)
        self.assertNotIn("gclid", result)
        self.assertIn("real=param", result)

    def test_removes_fragment(self):
        result = normalize_url("https://example.com/page#section")
        self.assertNotIn("#", result)

    def test_lowercases_hostname(self):
        result = normalize_url("https://Example.COM/Path")
        self.assertIn("example.com", result)

    def test_preserves_case_sensitive_path(self):
        result = normalize_url("https://example.com/CaseSensitive")
        self.assertIn("/CaseSensitive", result)

    def test_normalizes_trailing_slash_on_root(self):
        result = normalize_url("https://example.com")
        self.assertTrue(result.endswith("/"))

    def test_strips_trailing_slash_on_path(self):
        result = normalize_url("https://example.com/about/")
        self.assertFalse(result.endswith("/"))

    def test_resolves_relative_url(self):
        result = normalize_url("/services", base_url="https://example.com/about")
        self.assertEqual(result, "https://example.com/services")

    def test_collapses_double_slashes(self):
        result = normalize_url("https://example.com//path///page")
        self.assertNotIn("//path", result)

    def test_drops_default_port_https(self):
        result = normalize_url("https://example.com:443/page")
        self.assertNotIn(":443", result)

    def test_drops_default_port_http(self):
        result = normalize_url("http://example.com:80/page")
        self.assertNotIn(":80", result)

    def test_preserves_nonstandard_port(self):
        result = normalize_url("https://example.com:8080/page")
        self.assertIn(":8080", result)

    def test_empty_url_returns_empty(self):
        self.assertEqual(normalize_url(""), "")


class AllowedDomainsTests(unittest.TestCase):
    """Tests for get_allowed_domains in api.crawler.url_utils."""

    def test_www_url_returns_bare_and_www(self):
        result = get_allowed_domains("https://www.example.com")
        self.assertIn("example.com", result)
        self.assertIn("www.example.com", result)

    def test_bare_url_returns_bare_and_www(self):
        result = get_allowed_domains("https://example.com")
        self.assertIn("example.com", result)
        self.assertIn("www.example.com", result)

    def test_subdomain_url(self):
        result = get_allowed_domains("https://app.example.com")
        self.assertIn("app.example.com", result)

    def test_empty_url_returns_empty(self):
        self.assertEqual(get_allowed_domains(""), [])


class InternalURLTests(unittest.TestCase):
    """Tests for is_internal_url in api.crawler.url_utils."""

    def test_internal_url_matches(self):
        allowed = ["example.com", "www.example.com"]
        self.assertTrue(is_internal_url("https://example.com/about", allowed))
        self.assertTrue(is_internal_url("https://www.example.com/about", allowed))

    def test_external_url_rejected(self):
        allowed = ["example.com", "www.example.com"]
        self.assertFalse(is_internal_url("https://other.com/about", allowed))
        self.assertFalse(is_internal_url("https://linkedin.com/company/x", allowed))

    def test_empty_url_rejected(self):
        self.assertFalse(is_internal_url("", ["example.com"]))


class ExtractDomainTests(unittest.TestCase):
    def test_extracts_hostname(self):
        self.assertEqual(extract_domain("https://www.example.com/page"), "www.example.com")

    def test_empty_returns_empty(self):
        self.assertEqual(extract_domain(""), "")


# ═════════════════════════════════════════════════════════════════════════════
# Crawl Policy Tests
# ═════════════════════════════════════════════════════════════════════════════


class SkipURLTests(unittest.TestCase):
    """Tests for should_skip_url in api.crawler.policy."""

    def test_blocks_login_path(self):
        self.assertTrue(should_skip_url("https://example.com/login"))

    def test_blocks_cart_path(self):
        self.assertTrue(should_skip_url("https://example.com/cart"))

    def test_blocks_checkout_path(self):
        self.assertTrue(should_skip_url("https://example.com/checkout"))

    def test_blocks_admin_path(self):
        self.assertTrue(should_skip_url("https://example.com/wp-admin/dashboard"))

    def test_blocks_account_path(self):
        self.assertTrue(should_skip_url("https://example.com/account/settings"))

    def test_blocks_search_query(self):
        self.assertTrue(should_skip_url("https://example.com/results?search=test"))

    def test_blocks_image_extension(self):
        self.assertTrue(should_skip_url("https://example.com/logo.png"))

    def test_blocks_zip_extension(self):
        self.assertTrue(should_skip_url("https://example.com/file.zip"))

    def test_allows_services_path(self):
        self.assertFalse(should_skip_url("https://example.com/services"))

    def test_allows_about_path(self):
        self.assertFalse(should_skip_url("https://example.com/about"))

    def test_allows_html_extension(self):
        self.assertFalse(should_skip_url("https://example.com/page.html"))

    def test_allows_pdf_extension(self):
        self.assertFalse(should_skip_url("https://example.com/brochure.pdf"))

    def test_allows_root(self):
        self.assertFalse(should_skip_url("https://example.com/"))


class URLScoringTests(unittest.TestCase):
    """Tests for score_url in api.crawler.policy."""

    def test_homepage_gets_highest_score(self):
        score = score_url("https://example.com/")
        self.assertEqual(score, 100)

    def test_about_scores_high(self):
        self.assertGreater(score_url("https://example.com/about"), 50)

    def test_contact_scores_high(self):
        self.assertGreater(score_url("https://example.com/contact"), 50)

    def test_services_scores_high(self):
        self.assertGreater(score_url("https://example.com/services"), 50)

    def test_login_scores_very_negative(self):
        self.assertLess(score_url("https://example.com/login"), 0)

    def test_unknown_path_gets_moderate_score(self):
        score = score_url("https://example.com/some-random-page")
        self.assertGreater(score, 0)
        self.assertLess(score, 50)


class PageClassificationTests(unittest.TestCase):
    """Tests for classify_page_type in api.crawler.policy."""

    def test_homepage(self):
        self.assertEqual(classify_page_type("https://example.com/"), "homepage")

    def test_about_page(self):
        self.assertEqual(classify_page_type("https://example.com/about"), "about")

    def test_about_us_page(self):
        self.assertEqual(classify_page_type("https://example.com/about-us"), "about")

    def test_contact_page(self):
        self.assertEqual(classify_page_type("https://example.com/contact"), "contact")

    def test_services_page(self):
        self.assertEqual(classify_page_type("https://example.com/services"), "services")

    def test_faq_page(self):
        self.assertEqual(classify_page_type("https://example.com/faq"), "faq")

    def test_blog_page(self):
        self.assertEqual(classify_page_type("https://example.com/blog"), "blog")

    def test_unknown_page(self):
        self.assertEqual(classify_page_type("https://example.com/xyz123"), "other")

    def test_falls_back_to_title(self):
        self.assertEqual(classify_page_type("https://example.com/p/1", title="Contact Us"), "contact")

    def test_pricing_from_url(self):
        self.assertEqual(classify_page_type("https://example.com/pricing"), "pricing")

    def test_legal_page(self):
        self.assertEqual(classify_page_type("https://example.com/privacy"), "legal")


class SocialDomainTests(unittest.TestCase):
    """Tests for is_social_domain in api.crawler.policy."""

    def test_linkedin(self):
        self.assertTrue(is_social_domain("https://www.linkedin.com/company/acme"))

    def test_facebook(self):
        self.assertTrue(is_social_domain("https://facebook.com/acme"))

    def test_instagram(self):
        self.assertTrue(is_social_domain("https://www.instagram.com/acme"))

    def test_non_social(self):
        self.assertFalse(is_social_domain("https://example.com/about"))


# ═════════════════════════════════════════════════════════════════════════════
# API Tests
# ═════════════════════════════════════════════════════════════════════════════


class CrawlerAPITests(unittest.TestCase):
    """Tests for the onboarding crawler API endpoints."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("DATABASE_URL", "sqlite:///./test_crawler.db")
        os.environ["AISO_AUTO_CREATE_TABLES"] = "1"
        # Allow test client through TrustedHostMiddleware.
        os.environ["AISO_ALLOWED_HOSTS"] = "*"

        from api.database import Base, engine, SessionLocal
        import api.crawler.models  # noqa: F401 — register models
        Base.metadata.create_all(bind=engine)

        # Seed a test user and client.
        db = SessionLocal()
        from api.database import User, Client
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if not db.query(User).filter(User.id == "test-user-1").first():
            db.add(User(
                id="test-user-1",
                email="test@example.com",
                name="Test User",
                provider="credentials",
                plan_tier="pro",
                account_role="user",
                created_at=now,
            ))
        if not db.query(Client).filter(Client.id == "test-client-1").first():
            db.add(Client(
                id="test-client-1",
                user_id="test-user-1",
                name="Test Company",
                url="https://www.testcompany.com",
                industry="Technology",
                location="Boston, MA",
                created_at=now,
                updated_at=now,
            ))
        db.commit()
        db.close()

    def setUp(self):
        from fastapi.testclient import TestClient
        from api.main import app
        from api.auth import get_current_user_id

        # Override auth dependency to return test user.
        app.dependency_overrides[get_current_user_id] = lambda: "test-user-1"
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        from api.main import app
        from api.auth import get_current_user_id
        app.dependency_overrides.pop(get_current_user_id, None)

    def test_create_workspace_success(self):
        response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "test-client-1",
            "website_url": "https://www.testcompany.com",
            "consent_confirmed": True,
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["normalized_domain"], "testcompany.com")
        self.assertIn("testcompany.com", data["allowed_domains"])
        self.assertIn("www.testcompany.com", data["allowed_domains"])
        self.assertTrue(data["consent_confirmed"])
        # Store workspace_id for subsequent tests.
        self.__class__._workspace_id = data["workspace_id"]

    def test_create_workspace_rejects_no_consent(self):
        response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "test-client-1",
            "website_url": "https://www.testcompany.com",
            "consent_confirmed": False,
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("consent", response.json()["detail"].lower())

    def test_create_workspace_rejects_invalid_url(self):
        response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "test-client-1",
            "website_url": "ftp://invalid.com",
            "consent_confirmed": True,
        })
        self.assertEqual(response.status_code, 422)

    def test_create_workspace_rejects_unknown_client(self):
        response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "nonexistent-client",
            "website_url": "https://example.com",
            "consent_confirmed": True,
        })
        self.assertEqual(response.status_code, 404)

    def test_create_crawl_job_returns_queued(self):
        # First create a workspace.
        ws_response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "test-client-1",
            "website_url": "https://www.testcompany.com",
            "consent_confirmed": True,
        })
        workspace_id = ws_response.json()["workspace_id"]

        response = self.client.post(
            f"/api/v1/onboarding-workspaces/{workspace_id}/crawl-jobs",
            json={"crawl_mode": "standard", "max_pages": 50, "max_depth": 2},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "queued")
        self.assertEqual(data["crawl_mode"], "standard")
        self.assertEqual(data["max_pages"], 50)
        self.assertEqual(data["max_depth"], 2)
        self.__class__._job_id = data["job_id"]

    def test_create_crawl_job_rejects_invalid_mode(self):
        ws_response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "test-client-1",
            "website_url": "https://www.testcompany.com",
            "consent_confirmed": True,
        })
        workspace_id = ws_response.json()["workspace_id"]

        response = self.client.post(
            f"/api/v1/onboarding-workspaces/{workspace_id}/crawl-jobs",
            json={"crawl_mode": "aggressive_scrape"},
        )
        self.assertEqual(response.status_code, 422)

    def test_get_job_status_returns_structure(self):
        # Create workspace + job.
        ws_response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "test-client-1",
            "website_url": "https://www.testcompany.com",
            "consent_confirmed": True,
        })
        workspace_id = ws_response.json()["workspace_id"]
        job_response = self.client.post(
            f"/api/v1/onboarding-workspaces/{workspace_id}/crawl-jobs",
            json={},
        )
        job_id = job_response.json()["job_id"]

        response = self.client.get(f"/api/v1/crawl-jobs/{job_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Verify all required fields exist.
        for field in ("job_id", "status", "crawl_mode", "max_pages",
                      "pages_discovered", "pages_crawled", "warnings", "created_at"):
            self.assertIn(field, data)

    def test_get_nonexistent_job_returns_404(self):
        response = self.client.get("/api/v1/crawl-jobs/nonexistent-id")
        self.assertEqual(response.status_code, 404)

    def test_list_pages_returns_empty_list(self):
        ws_response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "test-client-1",
            "website_url": "https://www.testcompany.com",
            "consent_confirmed": True,
        })
        workspace_id = ws_response.json()["workspace_id"]
        job_response = self.client.post(
            f"/api/v1/onboarding-workspaces/{workspace_id}/crawl-jobs",
            json={},
        )
        job_id = job_response.json()["job_id"]

        response = self.client.get(f"/api/v1/crawl-jobs/{job_id}/pages")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pages"], [])

    def test_get_profile_returns_null(self):
        ws_response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "test-client-1",
            "website_url": "https://www.testcompany.com",
            "consent_confirmed": True,
        })
        workspace_id = ws_response.json()["workspace_id"]
        job_response = self.client.post(
            f"/api/v1/onboarding-workspaces/{workspace_id}/crawl-jobs",
            json={},
        )
        job_id = job_response.json()["job_id"]

        response = self.client.get(f"/api/v1/crawl-jobs/{job_id}/business-profile")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["profile"])

    def test_list_evidence_returns_empty(self):
        ws_response = self.client.post("/api/v1/onboarding-workspaces", json={
            "client_id": "test-client-1",
            "website_url": "https://www.testcompany.com",
            "consent_confirmed": True,
        })
        workspace_id = ws_response.json()["workspace_id"]
        job_response = self.client.post(
            f"/api/v1/onboarding-workspaces/{workspace_id}/crawl-jobs",
            json={},
        )
        job_id = job_response.json()["job_id"]

        response = self.client.get(f"/api/v1/crawl-jobs/{job_id}/evidence")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["evidence"], [])

    @classmethod
    def tearDownClass(cls):
        import os
        try:
            os.remove("test_crawler.db")
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    unittest.main()
