"""
Shared contract, retry helper, and link utilities for all AI providers.

Every provider module exposes a single function:
    query(question: str) -> ProviderResult
"""
import re
import time
from dataclasses import dataclass, field
from typing import Any


SENSITIVE_METADATA_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "key",
    "password",
    "secret",
    "token",
}


def _sanitize_metadata(value: Any) -> Any:
    """Return provider metadata with obvious secrets removed."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(marker in lowered for marker in SENSITIVE_METADATA_KEYS):
                clean[key_text] = "[redacted]"
            else:
                clean[key_text] = _sanitize_metadata(item)
        return clean
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value[:50]]
    if isinstance(value, tuple):
        return [_sanitize_metadata(item) for item in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass
class ProviderCitation:
    """Structured citation/source evidence returned by a provider."""

    url: str
    title: str | None = None
    cited_text: str | None = None
    source_rank: int | None = None
    origin: str = "native_citation"
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "cited_text": self.cited_text,
            "source_rank": self.source_rank,
            "origin": self.origin,
            "raw_metadata": _sanitize_metadata(self.raw_metadata),
        }


@dataclass
class ProviderSearchResult:
    """Structured search result evidence returned by a provider."""

    url: str
    title: str | None = None
    snippet: str | None = None
    query: str | None = None
    result_rank: int | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "query": self.query,
            "result_rank": self.result_rank,
            "raw_metadata": _sanitize_metadata(self.raw_metadata),
        }


@dataclass
class ProviderResult:
    """Uniform return type for every provider."""
    response: str = ""
    error: str = ""
    provider: str | None = None
    model: str | None = None
    web_search_used: bool | None = None
    search_queries: list[str] = field(default_factory=list)
    citations: list[ProviderCitation] = field(default_factory=list)
    search_results: list[ProviderSearchResult] = field(default_factory=list)
    usage_metadata: dict[str, Any] = field(default_factory=dict)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def safe_raw_metadata(self) -> dict[str, Any]:
        metadata = _sanitize_metadata(self.raw_metadata)
        return metadata if isinstance(metadata, dict) else {"value": metadata}

    def safe_usage_metadata(self) -> dict[str, Any]:
        metadata = _sanitize_metadata(self.usage_metadata)
        return metadata if isinstance(metadata, dict) else {"value": metadata}


def extract_markdown_links(text: str) -> list[tuple[str, str]]:
    """
    Extract all [text](url) markdown links from a string.
    Returns list of (link_text, url) tuples.
    Used by providers to verify/audit what links are present in a response.
    """
    return re.findall(r'\[([^\]]*)\]\(([^)]+)\)', text)


def append_sources_block(text: str, links: list[tuple[str, str]]) -> str:
    """
    Append a **Sources:** block to text for links not already embedded inline.
    links: list of (label, url) tuples.
    Deduplicates by URL. Skips links already present as markdown in the text.
    """
    if not links:
        return text

    # URLs already in the text as [text](url) — don't double-add
    already_embedded = {url for _, url in extract_markdown_links(text)}

    new_links = [
        f"[{label}]({url})"
        for label, url in links
        if url not in already_embedded
    ]

    if not new_links:
        return text

    return text.rstrip() + "\n\n**Sources:** " + " ".join(new_links)


def with_retries(fn, max_retries: int = 2, base_wait: float = 2.0) -> ProviderResult:
    """
    Call fn() which should return a ProviderResult.
    On exception, retry with exponential backoff (2^attempt * base_wait seconds).
    Returns a ProviderResult with error filled in if all retries exhausted.
    """
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait = base_wait * (2 ** attempt)
                time.sleep(wait)
    return ProviderResult(error=str(last_err))
