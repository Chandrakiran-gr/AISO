"""
Perplexity Sonar provider.
Perplexity's API is OpenAI-compatible — uses the openai SDK with a custom base URL.
No additional SDK required. Model 'sonar' performs real-time web search natively.

Citation extraction notes:
- Perplexity puts citation URLs in a non-standard 'citations' field on the response.
- With the OpenAI Python SDK, custom fields land in response.model_extra, NOT as
  direct attributes. getattr(response, 'citations') will always return None.
- We access response.model_extra['citations'] instead.
- Perplexity embeds inline numbered references [1][2][3] in the text corresponding
  to the citations list by 0-based index. We convert these to [[N]](url) markdown
  links so the downstream analysis pipeline can extract them.
"""
import os
import re
from typing import Any

from webish.providers.base import ProviderCitation, ProviderResult, ProviderSearchResult, with_retries

MODEL = os.environ.get("AISO_PERPLEXITY_MODEL", "sonar")
BASE_URL = "https://api.perplexity.ai"


def _inline_citations(text: str, citations: list[str]) -> str:
    """
    Convert Perplexity's inline [N] numeric references into [[N]](url) markdown links.
    E.g. 'Great tours [1][2]' → 'Great tours [[1]](https://url1.com) [[2]](https://url2.com)'

    Appends a Sources block for any citation URLs not referenced inline.
    """
    if not citations:
        return text

    referenced = set()

    def _replace(match):
        n = int(match.group(1))
        idx = n - 1  # Perplexity is 1-indexed
        if 0 <= idx < len(citations):
            referenced.add(idx)
            return f"[[{n}]]({citations[idx]})"
        return match.group(0)  # leave unchanged if out of range

    # Replace [N] references, but not ones already inside markdown links [[N]](url)
    text = re.sub(r'\[(\d+)\](?!\()', _replace, text)

    # Append any citations not referenced inline in the text
    unreferenced = [
        (f"[{i + 1}]", citations[i])
        for i in range(len(citations))
        if i not in referenced
    ]
    if unreferenced:
        extras = " ".join(f"[{label}]({url})" for label, url in unreferenced)
        text = text.rstrip() + f"\n\n**Sources:** {extras}"

    return text


def _structured_citations(citations: list[str]) -> list[ProviderCitation]:
    return [
        ProviderCitation(
            url=url,
            source_rank=index + 1,
            origin="native_citation",
            raw_metadata={"source": "model_extra.citations"},
        )
        for index, url in enumerate(citations)
        if url
    ]


def _structured_search_results(raw_results: Any) -> list[ProviderSearchResult]:
    results: list[ProviderSearchResult] = []
    if not isinstance(raw_results, list):
        return results
    for index, item in enumerate(raw_results):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        results.append(
            ProviderSearchResult(
                url=url,
                title=str(item.get("title") or "").strip() or None,
                snippet=str(item.get("snippet") or item.get("description") or "").strip() or None,
                result_rank=index + 1,
                raw_metadata=item,
            )
        )
    return results


def query(question: str) -> ProviderResult:
    """Query Perplexity Sonar API with correct citation extraction."""
    api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("PERPLEXITY_API_KEY is not set.")

    def _call() -> ProviderResult:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=BASE_URL)
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": question}],
        )
        text = response.choices[0].message.content or ""

        # Citations live in model_extra (non-standard Perplexity field).
        # getattr(response, 'citations') does NOT work with the OpenAI SDK.
        citations: list[str] = []
        search_results: list[ProviderSearchResult] = []
        raw_metadata = {}
        if hasattr(response, "model_extra") and response.model_extra:
            raw_metadata = dict(response.model_extra)
            citations = response.model_extra.get("citations") or []
            search_results = _structured_search_results(response.model_extra.get("search_results"))

        formatted = _inline_citations(text, citations)
        return ProviderResult(
            response=formatted,
            provider="perplexity",
            model=MODEL,
            web_search_used=bool(citations or search_results),
            citations=_structured_citations(citations),
            search_results=search_results,
            raw_metadata=raw_metadata,
        )

    return with_retries(_call)


def query_with_followup(question: str, followup: str) -> tuple[ProviderResult, ProviderResult]:
    """
    Two-turn conversation via Perplexity's OpenAI-compatible messages array.

    Round 1: user asks the question.
    Round 2: append assistant response + user follow-up to messages.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("PERPLEXITY_API_KEY is not set.")

    def _call() -> tuple[ProviderResult, ProviderResult]:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=BASE_URL)

        # Round 1
        resp1 = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": question}],
        )
        text1 = resp1.choices[0].message.content or ""
        citations1 = []
        search_results1: list[ProviderSearchResult] = []
        raw_metadata1 = {}
        if hasattr(resp1, "model_extra") and resp1.model_extra:
            raw_metadata1 = dict(resp1.model_extra)
            citations1 = resp1.model_extra.get("citations") or []
            search_results1 = _structured_search_results(resp1.model_extra.get("search_results"))
        formatted1 = _inline_citations(text1, citations1)
        r1 = ProviderResult(
            response=formatted1,
            provider="perplexity",
            model=MODEL,
            web_search_used=bool(citations1 or search_results1),
            citations=_structured_citations(citations1),
            search_results=search_results1,
            raw_metadata=raw_metadata1,
        )

        if not text1.strip():
            return r1, ProviderResult(error="round1_empty")

        # Round 2 — multi-turn messages
        resp2 = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "user", "content": question},
                {"role": "assistant", "content": text1},
                {"role": "user", "content": followup},
            ],
        )
        text2 = resp2.choices[0].message.content or ""
        citations2 = []
        search_results2: list[ProviderSearchResult] = []
        raw_metadata2 = {}
        if hasattr(resp2, "model_extra") and resp2.model_extra:
            raw_metadata2 = dict(resp2.model_extra)
            citations2 = resp2.model_extra.get("citations") or []
            search_results2 = _structured_search_results(resp2.model_extra.get("search_results"))
        formatted2 = _inline_citations(text2, citations2)
        r2 = ProviderResult(
            response=formatted2,
            provider="perplexity",
            model=MODEL,
            web_search_used=bool(citations2 or search_results2),
            citations=_structured_citations(citations2),
            search_results=search_results2,
            raw_metadata=raw_metadata2,
        )

        return r1, r2

    return with_retries(_call)
