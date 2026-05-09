"""robots.txt fetching and parsing for the onboarding crawler.

Provides robots.txt retrieval, directive parsing (Allow/Disallow),
and sitemap URL extraction — all without external dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse


# Type alias for a simple text fetcher used by the discovery layer.
# Signature: fetch(url) -> (status_code, text_body)
# Allows easy injection of fakes in tests.
TextFetcher = Callable[[str], tuple[int, str]]


@dataclass
class RobotsResult:
    """Parsed robots.txt directives for a single user-agent."""

    allowed: bool = True
    """Whether crawling the site root is broadly allowed."""

    sitemap_urls: list[str] = field(default_factory=list)
    """Sitemap URLs declared in the robots.txt file."""

    disallow_patterns: list[str] = field(default_factory=list)
    """Path prefixes disallowed by the matching user-agent group."""

    allow_patterns: list[str] = field(default_factory=list)
    """Path prefixes explicitly allowed (overrides Disallow)."""

    crawl_delay: float | None = None
    """Crawl-delay in seconds, if specified."""

    raw_text: str = ""
    """The original robots.txt content for debugging."""


# ── Fetching ─────────────────────────────────────────────────────────────────

def fetch_robots_txt(
    base_url: str,
    fetcher: TextFetcher,
) -> RobotsResult:
    """Fetch and parse the robots.txt for a website.

    Args:
        base_url: The website root URL (e.g. ``https://example.com``).
        fetcher: Callable that takes a URL and returns ``(status_code, body)``.

    Returns:
        A ``RobotsResult`` with parsed directives.  If the file is missing
        (404) or unreachable, returns a permissive default.
    """
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    try:
        status, body = fetcher(robots_url)
    except Exception:
        # Network errors → treat as permissive (no robots.txt).
        return RobotsResult(allowed=True, raw_text="")

    if status >= 500:
        # Server error → conservative: assume restricted.
        return RobotsResult(allowed=False, raw_text=body or "")

    if status == 404 or not body or not body.strip():
        return RobotsResult(allowed=True, raw_text=body or "")

    return parse_robots_txt(body)


# ── Parsing ──────────────────────────────────────────────────────────────────

_SITEMAP_RE = re.compile(r"^Sitemap:\s*(.+)", re.IGNORECASE)
_USER_AGENT_RE = re.compile(r"^User-agent:\s*(.+)", re.IGNORECASE)
_DISALLOW_RE = re.compile(r"^Disallow:\s*(.*)", re.IGNORECASE)
_ALLOW_RE = re.compile(r"^Allow:\s*(.*)", re.IGNORECASE)
_CRAWL_DELAY_RE = re.compile(r"^Crawl-delay:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def parse_robots_txt(
    text: str,
    user_agent: str = "AISOContextBot",
) -> RobotsResult:
    """Parse robots.txt content and return directives for *user_agent*.

    Matching priority:
      1. Exact user-agent match (case-insensitive).
      2. Wildcard ``*`` group.

    Sitemap directives are always collected regardless of user-agent scope.
    """
    result = RobotsResult(raw_text=text)

    # Collect sitemap URLs (global, not scoped to user-agent).
    for line in text.splitlines():
        line = line.strip()
        m = _SITEMAP_RE.match(line)
        if m:
            url = m.group(1).strip()
            if url and url not in result.sitemap_urls:
                result.sitemap_urls.append(url)

    # Parse user-agent groups.
    ua_lower = user_agent.lower()
    groups: dict[str, dict[str, list[str] | float | None]] = {}
    current_agents: list[str] = []
    _in_group = False

    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()  # Strip comments.
        if not line:
            # Blank line ends the current group.
            current_agents = []
            _in_group = False
            continue

        m = _USER_AGENT_RE.match(line)
        if m:
            agent = m.group(1).strip().lower()
            if not _in_group:
                # Starting a new group — reset agent list.
                current_agents = []
                _in_group = True
            current_agents.append(agent)
            if agent not in groups:
                groups[agent] = {"disallow": [], "allow": [], "crawl_delay": None}
            continue

        if not current_agents:
            continue

        m = _DISALLOW_RE.match(line)
        if m:
            path = m.group(1).strip()
            for agent in current_agents:
                groups[agent]["disallow"].append(path)
            continue

        m = _ALLOW_RE.match(line)
        if m:
            path = m.group(1).strip()
            for agent in current_agents:
                groups[agent]["allow"].append(path)
            continue

        m = _CRAWL_DELAY_RE.match(line)
        if m:
            delay = float(m.group(1))
            for agent in current_agents:
                groups[agent]["crawl_delay"] = delay
            continue

        # Unknown directive lines are ignored.

    # Select the best matching group.
    group = groups.get(ua_lower) or groups.get("*")
    if group is None:
        # No matching group → everything allowed.
        result.allowed = True
        return result

    result.disallow_patterns = [p for p in group["disallow"] if p]
    result.allow_patterns = [p for p in group["allow"] if p]
    result.crawl_delay = group.get("crawl_delay")

    # Determine if root is broadly allowed.
    if "/" in result.disallow_patterns and "/" not in result.allow_patterns:
        result.allowed = False
    else:
        result.allowed = True

    return result


def is_path_allowed(url: str, robots: RobotsResult) -> bool:
    """Check if a specific URL path is allowed by the parsed robots rules.

    Uses longest-match semantics: the longest matching Allow or Disallow
    pattern wins.  If no pattern matches, the URL is allowed.
    """
    if not robots.disallow_patterns and not robots.allow_patterns:
        return True

    path = urlparse(url).path or "/"

    best_match = ""
    best_allowed = True

    for pattern in robots.allow_patterns:
        if path.startswith(pattern) and len(pattern) > len(best_match):
            best_match = pattern
            best_allowed = True

    for pattern in robots.disallow_patterns:
        if path.startswith(pattern) and len(pattern) > len(best_match):
            best_match = pattern
            best_allowed = False

    return best_allowed
