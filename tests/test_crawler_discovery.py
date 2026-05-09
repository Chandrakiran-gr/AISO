"""Tests for crawler discovery engine — robots, sitemaps, links, candidates."""

import unittest
from api.crawler.robots import RobotsResult, fetch_robots_txt, parse_robots_txt, is_path_allowed
from api.crawler.discovery import (
    parse_sitemap_xml, discover_sitemap_urls,
    extract_homepage_links, discover_crawl_candidates,
)


def make_fetcher(pages: dict[str, tuple[int, str]]):
    """Create a fake TextFetcher from a URL→(status, body) dict."""
    def fetcher(url: str) -> tuple[int, str]:
        if url in pages:
            return pages[url]
        return (404, "")
    return fetcher


# ═════════════════════════════════════════════════════════════════════════════
# robots.txt Tests
# ═════════════════════════════════════════════════════════════════════════════

class RobotsFetchTests(unittest.TestCase):
    def test_missing_robots_returns_permissive(self):
        r = fetch_robots_txt("https://example.com", make_fetcher({}))
        self.assertTrue(r.allowed)

    def test_server_error_returns_restrictive(self):
        fetcher = make_fetcher({"https://example.com/robots.txt": (500, "")})
        r = fetch_robots_txt("https://example.com", fetcher)
        self.assertFalse(r.allowed)

    def test_network_error_returns_permissive(self):
        def bad_fetcher(url):
            raise ConnectionError("timeout")
        r = fetch_robots_txt("https://example.com", bad_fetcher)
        self.assertTrue(r.allowed)


class RobotsParseTests(unittest.TestCase):
    def test_disallow_root_blocks_crawl(self):
        r = parse_robots_txt("User-agent: *\nDisallow: /\n")
        self.assertFalse(r.allowed)

    def test_allow_root_permits_crawl(self):
        r = parse_robots_txt("User-agent: *\nAllow: /\n")
        self.assertTrue(r.allowed)

    def test_empty_robots_permits_crawl(self):
        r = parse_robots_txt("")
        self.assertTrue(r.allowed)

    def test_sitemap_urls_extracted(self):
        text = "Sitemap: https://example.com/sitemap.xml\nSitemap: https://example.com/sitemap2.xml\n"
        r = parse_robots_txt(text)
        self.assertEqual(len(r.sitemap_urls), 2)
        self.assertIn("https://example.com/sitemap.xml", r.sitemap_urls)

    def test_specific_user_agent_match(self):
        text = "User-agent: AISOContextBot\nDisallow: /private\n\nUser-agent: *\nDisallow: /\n"
        r = parse_robots_txt(text, user_agent="AISOContextBot")
        self.assertTrue(r.allowed)
        self.assertIn("/private", r.disallow_patterns)

    def test_crawl_delay_parsed(self):
        r = parse_robots_txt("User-agent: *\nCrawl-delay: 5\n")
        self.assertEqual(r.crawl_delay, 5.0)

    def test_comments_ignored(self):
        r = parse_robots_txt("# Comment\nUser-agent: *\nAllow: /\n# Another comment\n")
        self.assertTrue(r.allowed)


class RobotsPathTests(unittest.TestCase):
    def test_disallowed_path_blocked(self):
        r = RobotsResult(disallow_patterns=["/admin", "/private"])
        self.assertFalse(is_path_allowed("https://example.com/admin/dashboard", r))
        self.assertFalse(is_path_allowed("https://example.com/private/data", r))

    def test_allowed_path_passes(self):
        r = RobotsResult(disallow_patterns=["/admin"])
        self.assertTrue(is_path_allowed("https://example.com/about", r))

    def test_allow_overrides_disallow(self):
        r = RobotsResult(disallow_patterns=["/docs"], allow_patterns=["/docs/public"])
        self.assertTrue(is_path_allowed("https://example.com/docs/public/guide", r))
        self.assertFalse(is_path_allowed("https://example.com/docs/internal", r))

    def test_no_rules_permits_all(self):
        r = RobotsResult()
        self.assertTrue(is_path_allowed("https://example.com/anything", r))


# ═════════════════════════════════════════════════════════════════════════════
# Sitemap Tests
# ═════════════════════════════════════════════════════════════════════════════

class SitemapParseTests(unittest.TestCase):
    def test_urlset_extraction(self):
        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/about</loc></url>
          <url><loc>https://example.com/services</loc></url>
          <url><loc>https://example.com/contact</loc></url>
        </urlset>"""
        urls = parse_sitemap_xml(xml)
        self.assertEqual(len(urls), 3)
        self.assertIn("https://example.com/about", urls)

    def test_sitemapindex_extraction(self):
        xml = """<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
          <sitemap><loc>https://example.com/sitemap-blog.xml</loc></sitemap>
        </sitemapindex>"""
        urls = parse_sitemap_xml(xml)
        self.assertEqual(len(urls), 2)

    def test_invalid_xml_returns_empty(self):
        self.assertEqual(parse_sitemap_xml("not xml at all"), [])

    def test_empty_returns_empty(self):
        self.assertEqual(parse_sitemap_xml(""), [])

    def test_no_namespace_fallback(self):
        xml = "<urlset><url><loc>https://example.com/page</loc></url></urlset>"
        urls = parse_sitemap_xml(xml)
        self.assertEqual(len(urls), 1)


class SitemapDiscoveryTests(unittest.TestCase):
    def test_discovers_from_robots_sitemap(self):
        robots = RobotsResult(sitemap_urls=["https://example.com/sitemap.xml"])
        fetcher = make_fetcher({
            "https://example.com/sitemap.xml": (200, """<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://example.com/services</loc></url>
              <url><loc>https://example.com/about</loc></url>
            </urlset>"""),
        })
        urls = discover_sitemap_urls("https://example.com", robots, fetcher,
                                     ["example.com", "www.example.com"])
        self.assertIn("https://example.com/services", urls)
        self.assertIn("https://example.com/about", urls)

    def test_tries_default_sitemap_when_none_in_robots(self):
        robots = RobotsResult(sitemap_urls=[])
        fetcher = make_fetcher({
            "https://example.com/sitemap.xml": (200, """<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://example.com/pricing</loc></url>
            </urlset>"""),
        })
        urls = discover_sitemap_urls("https://example.com", robots, fetcher,
                                     ["example.com", "www.example.com"])
        self.assertIn("https://example.com/pricing", urls)

    def test_filters_external_urls(self):
        robots = RobotsResult()
        fetcher = make_fetcher({
            "https://example.com/sitemap.xml": (200, """<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://example.com/about</loc></url>
              <url><loc>https://external.com/page</loc></url>
            </urlset>"""),
        })
        urls = discover_sitemap_urls("https://example.com", robots, fetcher,
                                     ["example.com", "www.example.com"])
        self.assertIn("https://example.com/about", urls)
        self.assertNotIn("https://external.com/page", urls)

    def test_handles_missing_sitemap(self):
        robots = RobotsResult()
        urls = discover_sitemap_urls("https://example.com", robots,
                                     make_fetcher({}), ["example.com"])
        self.assertEqual(urls, [])


# ═════════════════════════════════════════════════════════════════════════════
# Homepage Link Extraction Tests
# ═════════════════════════════════════════════════════════════════════════════

class HomepageLinkTests(unittest.TestCase):
    def test_extracts_internal_links(self):
        html = '<a href="/about">About</a><a href="/services">Services</a>'
        internal, social = extract_homepage_links(html, "https://example.com/",
                                                  ["example.com", "www.example.com"])
        self.assertEqual(len(internal), 2)
        self.assertIn("https://example.com/about", internal)
        self.assertIn("https://example.com/services", internal)

    def test_skips_external_links(self):
        html = '<a href="https://other.com/page">Other</a><a href="/about">About</a>'
        internal, social = extract_homepage_links(html, "https://example.com/",
                                                  ["example.com"])
        self.assertEqual(len(internal), 1)
        self.assertIn("https://example.com/about", internal)

    def test_detects_social_links(self):
        html = '<a href="https://linkedin.com/company/acme">LinkedIn</a><a href="https://instagram.com/acme">IG</a>'
        internal, social = extract_homepage_links(html, "https://example.com/",
                                                  ["example.com"])
        self.assertEqual(len(social), 2)
        self.assertEqual(len(internal), 0)

    def test_deduplicates_links(self):
        html = '<a href="/about">A</a><a href="/about">B</a><a href="/about#section">C</a>'
        internal, _ = extract_homepage_links(html, "https://example.com/",
                                             ["example.com"])
        self.assertEqual(len(internal), 1)

    def test_skips_mailto_and_tel(self):
        html = '<a href="mailto:a@b.com">Email</a><a href="tel:123">Call</a><a href="/real">Real</a>'
        internal, _ = extract_homepage_links(html, "https://example.com/",
                                             ["example.com"])
        self.assertEqual(len(internal), 1)

    def test_resolves_relative_urls(self):
        html = '<a href="services/facial">Facial</a>'
        internal, _ = extract_homepage_links(html, "https://example.com/",
                                             ["example.com"])
        self.assertTrue(any("services/facial" in u for u in internal))

    def test_empty_html_returns_empty(self):
        internal, social = extract_homepage_links("", "https://example.com/",
                                                  ["example.com"])
        self.assertEqual(internal, [])
        self.assertEqual(social, [])


# ═════════════════════════════════════════════════════════════════════════════
# Full Discovery Tests
# ═════════════════════════════════════════════════════════════════════════════

class DiscoveryIntegrationTests(unittest.TestCase):
    def _make_site(self):
        return make_fetcher({
            "https://example.com/robots.txt": (200, "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml\n"),
            "https://example.com/sitemap.xml": (200, """<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://example.com/services</loc></url>
              <url><loc>https://example.com/about</loc></url>
              <url><loc>https://example.com/pricing</loc></url>
            </urlset>"""),
            "https://example.com/": (200, """<html><body>
              <a href="/contact">Contact</a>
              <a href="/faq">FAQ</a>
              <a href="https://linkedin.com/company/example">LinkedIn</a>
              <a href="https://other.com/page">External</a>
              <a href="/about">About</a>
            </body></html>"""),
        })

    def test_full_discovery_returns_candidates(self):
        r = discover_crawl_candidates("https://example.com", self._make_site())
        self.assertGreater(len(r.candidates), 0)
        urls = [c.url for c in r.candidates]
        self.assertIn("https://example.com/", urls)
        self.assertIn("https://example.com/services", urls)
        self.assertIn("https://example.com/about", urls)

    def test_external_urls_excluded(self):
        r = discover_crawl_candidates("https://example.com", self._make_site())
        urls = [c.url for c in r.candidates]
        self.assertNotIn("https://other.com/page", urls)

    def test_social_links_collected(self):
        r = discover_crawl_candidates("https://example.com", self._make_site())
        self.assertTrue(any("linkedin.com" in s for s in r.social_links))

    def test_duplicates_removed(self):
        r = discover_crawl_candidates("https://example.com", self._make_site())
        urls = [c.url for c in r.candidates]
        self.assertEqual(len(urls), len(set(urls)))

    def test_high_value_urls_first(self):
        r = discover_crawl_candidates("https://example.com", self._make_site())
        if len(r.candidates) >= 2:
            self.assertGreaterEqual(r.candidates[0].score, r.candidates[1].score)

    def test_homepage_ranked_highest(self):
        r = discover_crawl_candidates("https://example.com", self._make_site())
        self.assertEqual(r.candidates[0].url, "https://example.com/")

    def test_max_pages_limits_output(self):
        r = discover_crawl_candidates("https://example.com", self._make_site(), max_pages=3)
        self.assertLessEqual(len(r.candidates), 3)

    def test_robots_disallow_root_aborts(self):
        fetcher = make_fetcher({
            "https://example.com/robots.txt": (200, "User-agent: *\nDisallow: /\n"),
        })
        r = discover_crawl_candidates("https://example.com", fetcher)
        self.assertEqual(len(r.candidates), 0)
        self.assertTrue(any("robots" in w.lower() for w in r.warnings))

    def test_robots_disallowed_path_filtered(self):
        fetcher = make_fetcher({
            "https://example.com/robots.txt": (200, "User-agent: *\nDisallow: /private\n"),
            "https://example.com/sitemap.xml": (200, """<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://example.com/about</loc></url>
              <url><loc>https://example.com/private/data</loc></url>
            </urlset>"""),
            "https://example.com/": (200, "<html></html>"),
        })
        r = discover_crawl_candidates("https://example.com", fetcher)
        urls = [c.url for c in r.candidates]
        self.assertIn("https://example.com/about", urls)
        self.assertNotIn("https://example.com/private/data", urls)

    def test_skip_policy_filters_login_urls(self):
        fetcher = make_fetcher({
            "https://example.com/robots.txt": (200, "User-agent: *\nAllow: /\n"),
            "https://example.com/sitemap.xml": (404, ""),
            "https://example.com/": (200, '<a href="/login">Login</a><a href="/about">About</a>'),
        })
        r = discover_crawl_candidates("https://example.com", fetcher)
        urls = [c.url for c in r.candidates]
        self.assertNotIn("https://example.com/login", urls)
        self.assertIn("https://example.com/about", urls)

    def test_candidate_source_tracking(self):
        r = discover_crawl_candidates("https://example.com", self._make_site())
        sources = {c.source for c in r.candidates}
        self.assertIn("seed", sources)

    def test_sitemap_count_tracked(self):
        r = discover_crawl_candidates("https://example.com", self._make_site())
        self.assertGreater(r.sitemap_urls_found, 0)

    def test_homepage_link_count_tracked(self):
        r = discover_crawl_candidates("https://example.com", self._make_site())
        self.assertGreater(r.homepage_links_found, 0)


if __name__ == "__main__":
    unittest.main()
