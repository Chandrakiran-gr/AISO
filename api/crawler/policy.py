"""Crawl policy — URL skip rules, scoring, and page classification."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ── Skip rules ───────────────────────────────────────────────────────────────

SKIP_PATH_SEGMENTS = (
    "/login",
    "/signin",
    "/signup",
    "/register",
    "/cart",
    "/checkout",
    "/account",
    "/wp-admin",
    "/admin",
    "/search",
    "/tag/",
    "/category/",
    "/author/",
    "/privacy",
    "/terms",
    "/cookie",
    "/calendar",
    "/filter",
    "/sort",
)

SKIP_EXTENSIONS = frozenset({
    ".zip", ".exe", ".dmg",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".mp3", ".wav", ".flac",
    ".woff", ".woff2", ".ttf", ".eot",
    ".css", ".js",
})

ALLOW_EXTENSIONS = frozenset({".pdf", ".html", ".htm", ""})

# ── URL scoring ──────────────────────────────────────────────────────────────

HIGH_VALUE_KEYWORDS: dict[str, int] = {
    "": 100,           # homepage
    "about": 90,
    "contact": 90,
    "services": 85,
    "products": 85,
    "solutions": 80,
    "pricing": 75,
    "faq": 75,
    "help": 70,
    "docs": 70,
    "documentation": 70,
    "case-studies": 65,
    "case-study": 65,
    "customers": 65,
    "resources": 60,
    "blog": 50,
    "news": 50,
    "team": 45,
    "locations": 80,
    "location": 80,
    "support": 70,
    "menu": 75,
    "portfolio": 55,
    "testimonials": 65,
    "reviews": 65,
}

LOW_VALUE_KEYWORDS: dict[str, int] = {
    "login": -100,
    "signin": -100,
    "signup": -100,
    "register": -100,
    "cart": -100,
    "checkout": -100,
    "account": -100,
    "admin": -100,
    "wp-admin": -100,
    "privacy": -50,
    "terms": -50,
    "cookie": -50,
    "tag": -40,
    "category": -20,
    "author": -20,
    "search": -80,
    "filter": -60,
    "sort": -60,
    "calendar": -40,
}

# ── Page classification ──────────────────────────────────────────────────────

PAGE_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("homepage",      re.compile(r"^/?$")),
    ("about",         re.compile(r"\b(?:about|about-us|who-we-are|our-story)\b", re.I)),
    ("contact",       re.compile(r"\b(?:contact|contact-us|get-in-touch|reach-us)\b", re.I)),
    ("services",      re.compile(r"\b(?:services|service|what-we-do)\b", re.I)),
    ("products",      re.compile(r"\b(?:products|product|shop|store)\b", re.I)),
    ("solutions",     re.compile(r"\b(?:solutions|solution)\b", re.I)),
    ("pricing",       re.compile(r"\b(?:pricing|prices|plans|packages)\b", re.I)),
    ("faq",           re.compile(r"\b(?:faq|faqs|frequently-asked)\b", re.I)),
    ("blog",          re.compile(r"\b(?:blog|articles|insights|posts)\b", re.I)),
    ("news",          re.compile(r"\b(?:news|press|announcements|media)\b", re.I)),
    ("case_study",    re.compile(r"\b(?:case.?stud|success.?stor|portfolio)\b", re.I)),
    ("documentation", re.compile(r"\b(?:docs|documentation|help|guide|knowledge.?base)\b", re.I)),
    ("team",          re.compile(r"\b(?:team|staff|people|leadership)\b", re.I)),
    ("locations",     re.compile(r"\b(?:locations|offices|branches|find-us|stores|map)\b", re.I)),
    ("support",       re.compile(r"\b(?:support|help-center|helpdesk)\b", re.I)),
    ("legal",         re.compile(r"\b(?:privacy|terms|legal|disclaimer|cookie)\b", re.I)),
    ("testimonials",  re.compile(r"\b(?:testimonials|reviews|clients|feedback)\b", re.I)),
    ("careers",       re.compile(r"\b(?:careers|jobs|hiring|join.?us|work.?with)\b", re.I)),
]

# Social domains — stored as external links, never crawled.
SOCIAL_DOMAINS = frozenset({
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "pinterest.com",
    "threads.net",
})


def should_skip_url(url: str) -> bool:
    """Return True if the URL should be excluded from crawling."""
    parsed = urlparse(url)
    path = (parsed.path or "").lower()

    # Check skip path segments.
    for segment in SKIP_PATH_SEGMENTS:
        if segment in path:
            return True

    # Check file extension.
    dot_pos = path.rfind(".")
    if dot_pos > 0:
        ext = path[dot_pos:].lower()
        if ext in SKIP_EXTENSIONS:
            return True
        # Allow only known document extensions.
        if ext not in ALLOW_EXTENSIONS:
            return True

    # Check query string for search patterns.
    query = (parsed.query or "").lower()
    if "search=" in query:
        return True

    return False


def score_url(url: str) -> int:
    """Score a URL by path keywords. Higher = more important to crawl."""
    parsed = urlparse(url)
    path = (parsed.path or "").lower().strip("/")
    segments = [s for s in path.split("/") if s]

    # Homepage gets top score.
    if not segments:
        return HIGH_VALUE_KEYWORDS.get("", 50)

    score = 0
    matched = False

    for segment in segments:
        # Strip common extensions for matching.
        clean = re.sub(r"\.(html?|php|aspx?)$", "", segment, flags=re.I)
        if clean in HIGH_VALUE_KEYWORDS:
            score += HIGH_VALUE_KEYWORDS[clean]
            matched = True
        if clean in LOW_VALUE_KEYWORDS:
            score += LOW_VALUE_KEYWORDS[clean]
            matched = True

    # Penalize deep paths.
    depth_penalty = max(0, (len(segments) - 2)) * 5
    score -= depth_penalty

    # Default score for unmatched paths.
    if not matched:
        score = 30

    return score


def classify_page_type(url: str, title: str = "") -> str:
    """Classify a page by URL path and title heuristics.

    Returns one of the standard page types or ``"other"``.
    """
    parsed = urlparse(url)
    path = parsed.path or ""

    # Check URL path first (higher confidence).
    for page_type, pattern in PAGE_TYPE_PATTERNS:
        if pattern.search(path):
            return page_type

    # Fall back to title matching.
    if title:
        for page_type, pattern in PAGE_TYPE_PATTERNS:
            if pattern.search(title):
                return page_type

    return "other"


def is_social_domain(url: str) -> bool:
    """Return True if the URL points to a known social media platform."""
    hostname = (urlparse(url).hostname or "").lower().strip(".")
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in SOCIAL_DOMAINS
    )
