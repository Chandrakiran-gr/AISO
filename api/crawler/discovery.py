"""Crawl discovery engine — URL candidate collection without full page fetching.

This module orchestrates the discovery phase of a crawl job:
  1. Fetch and parse robots.txt
  2. Discover sitemaps (from robots.txt + default /sitemap.xml)
  3. Parse sitemap XML to extract URLs
  4. Extract links from the homepage HTML
  5. Score, filter, deduplicate, and rank all candidates
  6. Return a bounded set of crawl candidates

All HTTP I/O is injected via the ``TextFetcher`` callable so discovery
logic can be tested without real network access.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlparse

from api.crawler.policy import (
    is_social_domain,
    score_url,
    should_skip_url,
)
from api.crawler.robots import (
    RobotsResult,
    TextFetcher,
    fetch_robots_txt,
    is_path_allowed,
)
from api.crawler.url_utils import (
    extract_domain,
    get_allowed_domains,
    is_internal_url,
    normalize_url,
)


@dataclass
class CrawlCandidate:
    """A discovered URL that may be worth crawling."""

    url: str
    """Normalized URL."""

    score: int = 0
    """Priority score — higher is more important."""

    depth: int = 0
    """Depth from the seed URL (homepage = 0)."""

    source: str = ""
    """How this URL was discovered: ``sitemap``, ``homepage_link``, ``seed``."""


@dataclass
class DiscoveryResult:
    """Output of the URL discovery phase."""

    candidates: list[CrawlCandidate] = field(default_factory=list)
    """Scored, deduplicated, sorted crawl candidates."""

    robots: RobotsResult | None = None
    """Parsed robots.txt result."""

    sitemap_urls_found: int = 0
    """Number of URLs extracted from sitemaps."""

    homepage_links_found: int = 0
    """Number of internal links found on the homepage."""

    total_discovered: int = 0
    """Total unique URLs discovered before limit/filter."""

    warnings: list[str] = field(default_factory=list)
    """Non-fatal warnings from the discovery process."""

    social_links: list[str] = field(default_factory=list)
    """Social media URLs found on the homepage."""


# ── Sitemap parsing ──────────────────────────────────────────────────────────

# XML namespace used by the Sitemap protocol.
_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def parse_sitemap_xml(xml_text: str) -> list[str]:
    """Extract URLs from a sitemap XML document.

    Handles both ``<urlset>`` (leaf sitemaps) and ``<sitemapindex>``
    (sitemap index files).  Returns a flat list of URLs.
    """
    urls: list[str] = []
    if not xml_text or not xml_text.strip():
        return urls

    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return urls

    # Strip namespace prefix for matching.
    tag = re.sub(r"\{[^}]+\}", "", root.tag).lower()

    if tag == "urlset":
        for url_elem in root.findall("sm:url/sm:loc", _SITEMAP_NS):
            if url_elem.text and url_elem.text.strip():
                urls.append(url_elem.text.strip())
        # Fallback: try without namespace (some sitemaps omit it).
        if not urls:
            for url_elem in root.iter():
                if url_elem.tag.lower().endswith("loc") and url_elem.text:
                    urls.append(url_elem.text.strip())

    elif tag == "sitemapindex":
        # Sitemap index — extract child sitemap URLs.
        for loc in root.findall("sm:sitemap/sm:loc", _SITEMAP_NS):
            if loc.text and loc.text.strip():
                urls.append(loc.text.strip())
        if not urls:
            for loc in root.iter():
                if loc.tag.lower().endswith("loc") and loc.text:
                    urls.append(loc.text.strip())

    return urls


def discover_sitemap_urls(
    base_url: str,
    robots: RobotsResult,
    fetcher: TextFetcher,
    allowed_domains: list[str],
    *,
    max_sitemaps: int = 10,
) -> list[str]:
    """Discover URLs from sitemaps referenced in robots.txt + default path.

    Steps:
      1. Collect sitemap URLs from ``robots.sitemap_urls``.
      2. If none found, try the default ``/sitemap.xml``.
      3. Fetch each sitemap and parse URLs.
      4. If a sitemap is a sitemap index, recursively fetch child sitemaps
         (up to *max_sitemaps* total).
      5. Filter to internal URLs only.

    Returns a deduplicated list of normalized internal URLs.
    """
    sitemap_queue: list[str] = list(robots.sitemap_urls) if robots.sitemap_urls else []

    # Always try the default sitemap path if not already in the list.
    parsed = urlparse(base_url)
    default_sitemap = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    if default_sitemap not in sitemap_queue:
        sitemap_queue.append(default_sitemap)

    discovered: dict[str, None] = {}  # Ordered set via dict.
    sitemaps_fetched = 0

    while sitemap_queue and sitemaps_fetched < max_sitemaps:
        sitemap_url = sitemap_queue.pop(0)
        sitemaps_fetched += 1

        try:
            status, body = fetcher(sitemap_url)
        except Exception:
            continue

        if status != 200 or not body:
            continue

        urls = parse_sitemap_xml(body)

        for url in urls:
            norm = normalize_url(url)
            if not norm:
                continue

            # Check if it's a child sitemap (ends in .xml or contains sitemap).
            lower = norm.lower()
            if lower.endswith(".xml") or "sitemap" in lower:
                if norm not in {normalize_url(s) for s in sitemap_queue}:
                    sitemap_queue.append(url)
                continue

            # Only keep internal URLs.
            if is_internal_url(norm, allowed_domains):
                discovered[norm] = None

    return list(discovered.keys())


# ── Homepage link extraction ─────────────────────────────────────────────────


class _LinkExtractor(HTMLParser):
    """Minimal HTML parser that extracts <a href> values."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def extract_homepage_links(
    html: str,
    base_url: str,
    allowed_domains: list[str],
) -> tuple[list[str], list[str]]:
    """Extract internal and social links from a homepage HTML document.

    Args:
        html: Raw HTML content of the homepage.
        base_url: The homepage URL (used to resolve relative hrefs).
        allowed_domains: Domains considered internal.

    Returns:
        A tuple of ``(internal_urls, social_urls)`` — both deduplicated
        and normalized.
    """
    parser = _LinkExtractor()
    try:
        parser.feed(html or "")
    except Exception:
        pass

    internal: dict[str, None] = {}
    social: dict[str, None] = {}

    for href in parser.links:
        href = href.strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "sms:", "javascript:")):
            continue

        # Resolve relative URLs.
        resolved = normalize_url(href, base_url=base_url)
        if not resolved:
            continue

        # Classify: social vs internal vs external (dropped).
        if is_social_domain(resolved):
            social[resolved] = None
        elif is_internal_url(resolved, allowed_domains):
            internal[resolved] = None

    return list(internal.keys()), list(social.keys())


# ── Discovery orchestrator ───────────────────────────────────────────────────

def discover_crawl_candidates(
    website_url: str,
    fetcher: TextFetcher,
    *,
    max_pages: int = 100,
    max_depth: int = 3,
    allowed_domains: list[str] | None = None,
) -> DiscoveryResult:
    """Run the full URL discovery pipeline for a website.

    Steps:
      1. Derive allowed domains from the seed URL.
      2. Fetch and parse robots.txt.
      3. Abort if robots.txt disallows root crawling.
      4. Discover URLs from sitemaps.
      5. Fetch the homepage and extract links.
      6. Merge all candidates, deduplicate, filter, score, and sort.
      7. Apply max_pages limit.

    Args:
        website_url: The seed URL to discover from.
        fetcher: ``TextFetcher`` callable for HTTP requests.
        max_pages: Maximum number of candidates to return.
        max_depth: Maximum crawl depth (used to set candidate depth hints).
        allowed_domains: Override domain allowlist (auto-derived if None).

    Returns:
        A ``DiscoveryResult`` with scored, sorted candidates.
    """
    result = DiscoveryResult()

    # 1. Derive allowed domains.
    if allowed_domains is None:
        allowed_domains = get_allowed_domains(website_url)

    seed_url = normalize_url(website_url)
    if not seed_url:
        result.warnings.append("Invalid seed URL.")
        return result

    # 2. Fetch and parse robots.txt.
    robots = fetch_robots_txt(seed_url, fetcher)
    result.robots = robots

    # 3. Abort if robots disallows root.
    if not robots.allowed:
        result.warnings.append("Crawl blocked by robots.txt — root is disallowed.")
        return result

    # All discovered URLs → depth mapping.
    seen: dict[str, int] = {}  # normalized_url → depth

    # Add seed URL.
    seen[seed_url] = 0

    # 4. Discover from sitemaps.
    sitemap_urls = discover_sitemap_urls(
        seed_url, robots, fetcher, allowed_domains,
    )
    for url in sitemap_urls:
        if url not in seen:
            seen[url] = 1  # Sitemap URLs are depth 1 (one hop from homepage).
    result.sitemap_urls_found = len(sitemap_urls)

    # 5. Fetch homepage and extract links.
    try:
        status, homepage_html = fetcher(seed_url)
        if status == 200 and homepage_html:
            internal_links, social_links = extract_homepage_links(
                homepage_html, seed_url, allowed_domains,
            )
            for url in internal_links:
                if url not in seen:
                    seen[url] = 1  # Direct homepage links are depth 1.
            result.homepage_links_found = len(internal_links)
            result.social_links = social_links
    except Exception:
        result.warnings.append("Failed to fetch homepage for link extraction.")

    result.total_discovered = len(seen)

    # 6. Filter, score, and sort.
    candidates: list[CrawlCandidate] = []
    for url, depth in seen.items():
        # Depth limit.
        if depth > max_depth:
            continue

        # Policy filter.
        if should_skip_url(url):
            continue

        # Robots filter.
        if not is_path_allowed(url, robots):
            continue

        candidates.append(CrawlCandidate(
            url=url,
            score=score_url(url),
            depth=depth,
            source="seed" if url == seed_url else (
                "sitemap" if url in set(sitemap_urls) else "homepage_link"
            ),
        ))

    # Sort: highest score first, then shallowest depth.
    candidates.sort(key=lambda c: (-c.score, c.depth))

    # 7. Apply max_pages limit.
    result.candidates = candidates[:max_pages]

    return result
