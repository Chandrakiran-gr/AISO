"""
Shared contract, retry helper, and link utilities for all AI providers.

Every provider module exposes a single function:
    query(question: str) -> ProviderResult
"""
import re
import time
from dataclasses import dataclass


@dataclass
class ProviderResult:
    """Uniform return type for every provider."""
    response: str = ""
    error: str = ""


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
