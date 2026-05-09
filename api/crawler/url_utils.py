"""URL normalization and domain utilities for the onboarding crawler."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

# Tracking parameters stripped during normalization.
TRACKING_PARAMS = frozenset({
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "msclkid",
    "ref",
})


def normalize_url(url: str, *, base_url: str | None = None) -> str:
    """Normalize a URL for deduplication and comparison.

    Rules applied:
      - Resolve relative URLs against *base_url* when provided.
      - Lowercase scheme and hostname.
      - Remove fragment.
      - Remove tracking query parameters.
      - Normalize trailing slash (keep ``/`` for root, strip for paths).
      - Collapse repeated slashes in path.
    """
    raw = str(url or "").strip()
    if not raw:
        return ""

    # Resolve relative URLs when a base is given.
    if base_url and not re.match(r"^https?://", raw, re.I):
        raw = urljoin(base_url, raw)

    parsed = urlparse(raw)

    scheme = (parsed.scheme or "https").lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port

    # Rebuild netloc: drop default ports.
    if port and ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        port = None
    netloc = f"{hostname}:{port}" if port else hostname

    # Clean path: collapse double slashes, normalize trailing slash.
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    # Strip tracking query parameters.
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned = {
            key: values
            for key, values in params.items()
            if key.lower() not in TRACKING_PARAMS
        }
        query = urlencode(cleaned, doseq=True) if cleaned else ""
    else:
        query = ""

    # Never keep fragment.
    return urlunparse((scheme, netloc, path, "", query, ""))


def get_allowed_domains(website_url: str) -> list[str]:
    """Derive the set of allowed crawl domains from the seed URL.

    Given ``https://www.clientcompany.com``, returns::

        ["clientcompany.com", "www.clientcompany.com"]
    """
    hostname = (urlparse(website_url).hostname or "").lower().strip(".")
    if not hostname:
        return []

    domains: list[str] = []
    bare = hostname.removeprefix("www.")
    if bare:
        domains.append(bare)
    if hostname != bare:
        domains.append(hostname)
    elif f"www.{bare}" not in domains:
        domains.append(f"www.{bare}")

    return domains


def is_internal_url(url: str, allowed_domains: list[str]) -> bool:
    """Return True if *url* belongs to one of the *allowed_domains*."""
    hostname = (urlparse(url).hostname or "").lower().strip(".")
    if not hostname:
        return False
    return hostname in allowed_domains


def extract_domain(url: str) -> str:
    """Return the bare hostname from a URL."""
    return (urlparse(url).hostname or "").lower().strip(".")
