"""
Google Gemini provider.
Uses the google.generativeai SDK (officially deprecated but still functional).
Generates content using Gemini model.
"""
import os
from typing import Any

from webish.providers.base import ProviderCitation, ProviderResult, ProviderSearchResult, with_retries

MODEL = os.environ.get("AISO_GEMINI_MODEL", "gemini-2.5-flash")


def _extract_grounding_links(response) -> list[tuple[str, str]]:
    """
    Extract (title, url) pairs from Gemini's Search Grounding metadata.

    Note: Gemini returns Google proxy redirect URLs (vertexaisearch.cloud.google.com)
    instead of the real source URLs. However, the `title` field contains the actual
    domain name (e.g. 'calcoastadventures.com'). We construct a clean direct URL
    from the domain so the output matches the readable format of other providers.
    """
    try:
        candidates = response.candidates
        if not candidates:
            return []
        metadata = candidates[0].grounding_metadata
        if not metadata:
            return []
        chunks = metadata.grounding_chunks or []
        links = []
        seen_domains = set()
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if not web:
                continue
            title = (getattr(web, "title", "") or "").strip()
            redirect_url = (getattr(web, "uri", "") or "").strip()

            # Prefer clean direct domain URL over Google's opaque redirect proxy.
            # title usually holds the domain (e.g. "calcoastadventures.com").
            if title and "." in title and " " not in title:
                url = title if title.startswith("http") else f"https://{title}"
            elif redirect_url:
                url = redirect_url
            else:
                continue

            display = title or url
            # Deduplicate by domain
            domain = title or url
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            links.append((display, url))
        return links
    except (AttributeError, IndexError, TypeError):
        return []


def _dump_response(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        try:
            data = response.model_dump()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    if hasattr(response, "to_dict"):
        try:
            data = response.to_dict()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _extract_grounding_evidence(response: Any) -> tuple[list[ProviderCitation], list[ProviderSearchResult], list[str], dict[str, Any], bool]:
    raw_metadata = _dump_response(response)
    citations: list[ProviderCitation] = []
    search_results: list[ProviderSearchResult] = []
    search_queries: list[str] = []
    seen_urls: set[str] = set()

    for node in _walk(raw_metadata):
        if node.get("webSearchQueries") and isinstance(node.get("webSearchQueries"), list):
            for query in node["webSearchQueries"]:
                query_text = str(query).strip()
                if query_text and query_text not in search_queries:
                    search_queries.append(query_text)
        web = node.get("web")
        if isinstance(web, dict):
            url = str(web.get("uri") or "").strip()
            title = str(web.get("title") or "").strip() or None
            if title and "." in title and " " not in title:
                url = title if title.startswith("http") else f"https://{title}"
            if url.startswith(("http://", "https://")) and url not in seen_urls:
                seen_urls.add(url)
                citations.append(
                    ProviderCitation(
                        url=url,
                        title=title,
                        source_rank=len(citations) + 1,
                        origin="native_citation",
                        raw_metadata=node,
                    )
                )
        elif str(node.get("uri") or "").startswith(("http://", "https://")):
            url = str(node.get("uri")).strip()
            if url not in seen_urls:
                seen_urls.add(url)
                search_results.append(
                    ProviderSearchResult(
                        url=url,
                        title=str(node.get("title") or "").strip() or None,
                        snippet=str(node.get("snippet") or "").strip() or None,
                        query=search_queries[-1] if search_queries else None,
                        result_rank=len(search_results) + 1,
                        raw_metadata=node,
                    )
                )

    # Deprecated SDK objects do not always dump grounding metadata cleanly.
    if not citations:
        for title, url in _extract_grounding_links(response):
            citations.append(
                ProviderCitation(
                    url=url,
                    title=title,
                    source_rank=len(citations) + 1,
                    origin="native_citation",
                    raw_metadata={"source": "grounding_metadata"},
                )
            )

    return citations, search_results, search_queries, raw_metadata, bool(citations or search_results or search_queries)


def _build_result(response: Any, text: str) -> ProviderResult:
    citations, search_results, search_queries, raw_metadata, web_search_used = _extract_grounding_evidence(response)
    return ProviderResult(
        response=text,
        provider="gemini",
        model=MODEL,
        web_search_used=web_search_used,
        search_queries=search_queries,
        citations=citations,
        search_results=search_results,
        raw_metadata=raw_metadata,
    )


def _generate_grounded_content(api_key: str, question: str):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(tools=[grounding_tool])
    return client.models.generate_content(
        model=MODEL,
        contents=question,
        config=config,
    )


def _generate_grounded_content_fallback(api_key: str, question: str):
    from google.generativeai.client import configure
    from google.generativeai.generative_models import GenerativeModel

    configure(api_key=api_key)
    model = GenerativeModel(MODEL)
    return model.generate_content(question)


def query(question: str) -> ProviderResult:
    """Query Google Gemini and return response."""
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY is not set.")

    def _call() -> ProviderResult:
        try:
            response = _generate_grounded_content(api_key, question)
        except ImportError:
            response = _generate_grounded_content_fallback(api_key, question)
        text = response.text or ""

        return _build_result(response, text)

    return with_retries(_call)


def query_with_followup(question: str, followup: str) -> tuple[ProviderResult, ProviderResult]:
    """
    Two-turn conversation via Gemini's chat API.

    Round 1: send_message(question)
    Round 2: send_message(followup) — same chat session, Gemini remembers context.
    """
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY is not set.")

    def _call() -> tuple[ProviderResult, ProviderResult]:
        try:
            response1 = _generate_grounded_content(api_key, question)
        except ImportError:
            response1 = _generate_grounded_content_fallback(api_key, question)
        text1 = response1.text or ""
        r1 = _build_result(response1, text1)

        if not text1.strip():
            return r1, ProviderResult(error="round1_empty")

        try:
            response2 = _generate_grounded_content(api_key, followup)
        except ImportError:
            response2 = _generate_grounded_content_fallback(api_key, followup)
        text2 = response2.text or ""
        r2 = _build_result(response2, text2)

        return r1, r2

    return with_retries(_call)
