import socket
import unittest

from api.website_ingestion import (
    FetchResult,
    IngestionConfig,
    URLSafetyError,
    detect_stop_reason,
    discover_website,
    extract_html_evidence,
    fetch_public_page,
    should_use_playwright_fallback,
    validate_public_url,
)


def public_resolver(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


class WebsiteIngestionTests(unittest.TestCase):
    def test_url_safety_blocks_private_local_metadata_and_non_http(self):
        unsafe = [
            "http://localhost",
            "http://127.0.0.1",
            "http://169.254.169.254/latest/meta-data",
            "http://example.com:abc",
            "file:///etc/passwd",
            "ftp://example.com",
        ]

        for url in unsafe:
            with self.subTest(url=url):
                with self.assertRaises(URLSafetyError):
                    validate_public_url(url, resolver=public_resolver)

        self.assertEqual(
            validate_public_url("https://example.com", resolver=public_resolver),
            "https://example.com/",
        )

    def test_dom_extractor_collects_static_services_json_ld_and_ctas(self):
        html = """
        <html>
          <head>
            <title>PemSpa</title>
            <script type="application/ld+json">
              {"@type":"LocalBusiness","name":"Pempsa","address":{"addressLocality":"Newton Centre","addressRegion":"MA"}}
            </script>
          </head>
          <body>
            <nav><a href="/services">Services</a><a href="/book">Book now</a></nav>
            <h1>Customized facial spa</h1>
            <h2>Signature Facials</h2>
            <p>Chemical Peel $175 50 minutes</p>
            <button>Schedule appointment</button>
          </body>
        </html>
        """

        evidence = extract_html_evidence(html, "https://pempsa.example/")

        self.assertEqual(evidence["title"], "PemSpa")
        self.assertIn("Signature Facials", evidence["headings"])
        self.assertIn("Chemical Peel $175 50 minutes", evidence["text_blocks"])
        self.assertEqual(evidence["links"][1]["text"], "Book now")
        self.assertEqual(evidence["json_ld"][0]["name"], "Pempsa")

    def test_stop_conditions_detect_sensitive_pages(self):
        self.assertEqual(detect_stop_reason("Please log in to continue", []), "log in")
        self.assertEqual(
            detect_stop_reason(
                "Book appointment",
                [{"inputs": [{"type": "password", "name": "account_password"}]}],
            ),
            "sensitive form",
        )

    def test_stop_detection_allows_marketing_page_with_account_nav(self):
        text = " ".join(
            [
                "PemSpa Skincare & Wellness",
                "Sign In",
                "My Account",
                "Signature Facials",
                "Advanced Facials",
                "Chemical Peel",
                "Deluxe Dermaplane Facial",
                "Proudly serving Newton, Chestnut Hill, Brookline, and Needham.",
            ]
            * 30
        )

        self.assertIsNone(detect_stop_reason(text, []))

    def test_playwright_fallback_triggers_are_explicit(self):
        short_html = "<html><body><h1>Loading</h1></body></html>"
        fallback, reason = should_use_playwright_fallback(
            short_html,
            extract_html_evidence(short_html, "https://example.com/"),
        )
        self.assertTrue(fallback)
        self.assertEqual(reason, "static_body_text_below_500")

        empty_root_html = (
            "<html><body>"
            + ("Visible launch copy. " * 80)
            + "<div id='root'></div></body></html>"
        )
        fallback, reason = should_use_playwright_fallback(
            empty_root_html,
            extract_html_evidence(empty_root_html, "https://example.com/"),
        )
        self.assertTrue(fallback)
        self.assertEqual(reason, "empty_app_root")

        low_ratio_html = (
            "<html><body><h1>Real copy that is comfortably over five hundred characters "
            + ("for the parser and static body text. " * 20)
            + "</h1>"
            + ("<span data-noise='x'></span>" * 800)
            + "</body></html>"
        )
        fallback, reason = should_use_playwright_fallback(
            low_ratio_html,
            extract_html_evidence(low_ratio_html, "https://example.com/"),
        )
        self.assertTrue(fallback)
        self.assertEqual(reason, "text_to_html_ratio_below_5_percent")

    def test_discovery_respects_robots_and_sitemap_fixtures(self):
        pages = {
            "https://example.com/robots.txt": "User-agent: *\nAllow: /\n",
            "https://example.com/sitemap.xml": """
              <urlset><url><loc>https://example.com/services</loc></url></urlset>
            """,
            "https://example.com/": "<h1>Home</h1><a href='/book'>Book</a>",
            "https://example.com/services": "<h2>Services</h2><p>Deluxe Dermaplane Facial $145 45 minutes</p>",
            "https://example.com/book": "<h2>Book online</h2><p>Chemical Peel $175 50 minutes</p>",
        }

        def fetcher(url: str, config: IngestionConfig) -> FetchResult:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                text=pages[url],
            )

        evidence = discover_website(
            "https://example.com",
            config=IngestionConfig(max_pages=4),
            fetch_page=fetcher,
            resolver=public_resolver,
        )

        self.assertGreaterEqual(evidence["page_count"], 2)
        urls = {page["url"] for page in evidence["pages"]}
        self.assertIn("https://example.com/services", urls)

    def test_discovery_caps_playwright_fallback_to_five_pages(self):
        calls = {"rendered": 0}

        def fetcher(url: str, config: IngestionConfig) -> FetchResult:
            if url.endswith("/robots.txt") or url.endswith("/sitemap.xml"):
                return FetchResult(url=url, final_url=url, status_code=404, content_type="text/plain", text="")
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                text="<html><body><div id='root'></div></body></html>",
            )

        def renderer(url: str, config: IngestionConfig) -> FetchResult:
            calls["rendered"] += 1
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html; rendered=playwright",
                text="<html><body><h1>Rendered app page</h1><p>Useful rendered content.</p></body></html>",
            )

        evidence = discover_website(
            "https://example.com",
            config=IngestionConfig(max_pages=7, max_playwright_pages=99),
            fetch_page=fetcher,
            render_page=renderer,
            resolver=public_resolver,
        )

        self.assertEqual(calls["rendered"], 5)
        self.assertEqual(evidence["playwright_invocations"], 5)
        self.assertIn("Rendered DOM extraction skipped after the 5-page Playwright fallback limit.", evidence["warnings"])

    def test_discovery_follows_public_booking_cta_on_allowlisted_platform(self):
        pages = {
            "https://example.com/robots.txt": "User-agent: *\nAllow: /\n",
            "https://example.com/sitemap.xml": "<urlset></urlset>",
            "https://example.com/": """
              <h1>PemSpa</h1>
              <a href="https://pempsa.glossgenius.com/services">Schedule appointment</a>
            """,
            "https://pempsa.glossgenius.com/services": """
              <h1>Book online</h1>
              <p>Chemical Peel $175 50 minutes</p>
            """,
        }

        def fetcher(url: str, config: IngestionConfig) -> FetchResult:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                text=pages[url],
            )

        evidence = discover_website(
            "https://example.com",
            config=IngestionConfig(max_pages=4),
            fetch_page=fetcher,
            resolver=public_resolver,
        )

        urls = {page["url"] for page in evidence["pages"]}
        self.assertIn("https://pempsa.glossgenius.com/services", urls)

    def test_discovery_skips_non_allowlisted_external_cta(self):
        pages = {
            "https://example.com/robots.txt": "User-agent: *\nAllow: /\n",
            "https://example.com/sitemap.xml": "<urlset></urlset>",
            "https://example.com/": """
              <h1>PemSpa</h1>
              <a href="https://external.example/services">Book services</a>
            """,
        }

        def fetcher(url: str, config: IngestionConfig) -> FetchResult:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                text=pages[url],
            )

        evidence = discover_website(
            "https://example.com",
            config=IngestionConfig(max_pages=4),
            fetch_page=fetcher,
            resolver=public_resolver,
        )

        urls = {page["url"] for page in evidence["pages"]}
        self.assertNotIn("https://external.example/services", urls)

    def test_fetch_rechecks_resolution_before_connecting(self):
        calls = {"count": 0}

        def rebinding_resolver(host, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.10", 0))]

        with self.assertRaises(URLSafetyError):
            fetch_public_page(
                "https://example.com",
                IngestionConfig(timeout_seconds=0.1),
                resolver=rebinding_resolver,
            )

    def test_discovery_stops_when_robots_disallows_root(self):
        def fetcher(url: str, config: IngestionConfig) -> FetchResult:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/plain",
                text="User-agent: *\nDisallow: /\n",
            )

        evidence = discover_website(
            "https://example.com",
            fetch_page=fetcher,
            resolver=public_resolver,
        )

        self.assertEqual(evidence["page_count"], 0)
        self.assertIn("Crawl limited by robots/access rules.", evidence["warnings"])


if __name__ == "__main__":
    unittest.main()
