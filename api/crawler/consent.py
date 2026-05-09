"""Consent and URL safety validation for onboarding crawl requests."""

from __future__ import annotations

from urllib.parse import urlparse

from api.crawler.url_utils import get_allowed_domains, normalize_url


def validate_crawl_request(
    website_url: str,
    consent_confirmed: bool,
) -> dict[str, object]:
    """Validate a crawl request and return normalized crawl parameters.

    Returns::

        {
            "safe_url": "https://www.example.com/",
            "normalized_domain": "example.com",
            "allowed_domains": ["example.com", "www.example.com"],
        }

    Raises ``ValueError`` with a descriptive message on failure.
    """
    # 1. Consent is mandatory.
    if not consent_confirmed:
        raise ValueError(
            "Website owner consent is required before crawling. "
            "Please confirm that you are authorized to crawl this website."
        )

    # 2. URL must be present.
    raw_url = str(website_url or "").strip()
    if not raw_url:
        raise ValueError("A website URL is required.")

    # 3. Must be http or https.
    if not raw_url.startswith(("http://", "https://")):
        # Attempt to prepend https if no scheme.
        if "://" not in raw_url:
            raw_url = f"https://{raw_url}"
        else:
            raise ValueError("Only http and https URLs are supported.")

    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are supported.")

    if not parsed.hostname:
        raise ValueError("The URL must include a valid hostname.")

    # 4. SSRF protection — block private/local/internal hosts.
    hostname = parsed.hostname.lower()
    _reject_unsafe_host(hostname)

    # 5. Normalize and derive domains.
    safe_url = normalize_url(raw_url)
    allowed = get_allowed_domains(safe_url)
    bare_domain = hostname.removeprefix("www.")

    return {
        "safe_url": safe_url,
        "normalized_domain": bare_domain,
        "allowed_domains": allowed,
    }


def _reject_unsafe_host(hostname: str) -> None:
    """Raise ValueError if hostname is private, local, or internal."""
    from ipaddress import ip_address

    blocked_hosts = {
        "localhost",
        "localhost.localdomain",
        "0.0.0.0",
    }

    if hostname in blocked_hosts:
        raise ValueError("Private, local, or internal hosts are not allowed.")

    if hostname.endswith((".local", ".localhost", ".internal", ".test")):
        raise ValueError("Private, local, or internal hosts are not allowed.")

    # Check if hostname is a raw IP address.
    try:
        addr = ip_address(hostname.strip("[]"))
    except ValueError:
        # Not an IP literal — hostname is fine.
        return

    if addr.is_loopback or addr.is_private or addr.is_reserved or addr.is_link_local:
        raise ValueError("Private, local, or internal hosts are not allowed.")

    if not addr.is_global:
        raise ValueError("Private, local, or internal hosts are not allowed.")
