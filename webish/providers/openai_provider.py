"""
OpenAI provider — uses the Responses API with the web_search_preview tool.

Web search is explicitly enabled on every call via tool configuration.
This guarantees live web results regardless of model choice, consistent with
how real users experience ChatGPT with "Web search" toggled on.

The Responses API (client.responses.create) is newer than Chat Completions and
has native web search support. response.output_text returns the final answer
with inline [text](url) citation links already embedded by the model.
"""
import os
from typing import Any

from webish.providers.base import ProviderCitation, ProviderResult, ProviderSearchResult, with_retries

MODEL = os.environ.get("AISO_OPENAI_MODEL", "gpt-4o-mini")
WEB_SEARCH_TOOL_TYPE = os.environ.get("AISO_OPENAI_WEB_SEARCH_TOOL", "web_search_preview")


def _dump_response(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        try:
            data = response.model_dump()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    if isinstance(response, dict):
        return response
    return {}


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _extract_evidence(data: dict[str, Any]) -> tuple[list[ProviderCitation], list[ProviderSearchResult], list[str], bool]:
    citations: list[ProviderCitation] = []
    search_results: list[ProviderSearchResult] = []
    search_queries: list[str] = []
    web_search_used = False
    seen_citations: set[str] = set()
    seen_results: set[str] = set()

    for node in _walk(data):
        node_type = str(node.get("type") or "")
        if "web_search" in node_type:
            web_search_used = True
        action = node.get("action")
        if isinstance(action, dict) and action.get("query"):
            query = str(action.get("query")).strip()
            if query and query not in search_queries:
                search_queries.append(query)
        if node.get("query") and ("search" in node_type or "web" in node_type):
            query = str(node.get("query")).strip()
            if query and query not in search_queries:
                search_queries.append(query)

        url = str(node.get("url") or node.get("uri") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        title = str(node.get("title") or node.get("text") or "").strip() or None
        cited_text = str(node.get("cited_text") or node.get("snippet") or node.get("summary") or "").strip() or None
        if node_type in {"url_citation", "citation"} or "citation" in node_type or "annotation" in node_type:
            if url not in seen_citations:
                seen_citations.add(url)
                citations.append(
                    ProviderCitation(
                        url=url,
                        title=title,
                        cited_text=cited_text,
                        source_rank=len(citations) + 1,
                        origin="native_citation",
                        raw_metadata=node,
                    )
                )
        elif "search" in node_type or "result" in node_type or node.get("snippet"):
            if url not in seen_results:
                seen_results.add(url)
                search_results.append(
                    ProviderSearchResult(
                        url=url,
                        title=title,
                        snippet=cited_text,
                        query=search_queries[-1] if search_queries else None,
                        result_rank=len(search_results) + 1,
                        raw_metadata=node,
                    )
                )

    return citations, search_results, search_queries, web_search_used or bool(citations or search_results)


def _build_result(response: Any, text: str) -> ProviderResult:
    raw_metadata = _dump_response(response)
    citations, search_results, search_queries, web_search_used = _extract_evidence(raw_metadata)
    return ProviderResult(
        response=text,
        provider="openai",
        model=MODEL,
        web_search_used=web_search_used,
        search_queries=search_queries,
        citations=citations,
        search_results=search_results,
        raw_metadata=raw_metadata,
    )


def query(question: str) -> ProviderResult:
    """Query OpenAI with web search always enabled via the Responses API."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    def _call() -> ProviderResult:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model=MODEL,
            tools=[{"type": WEB_SEARCH_TOOL_TYPE}],  # web search always on
            input=question,
        )

        # output_text is a convenience property returning the final text response.
        # OpenAI embeds citation links inline as [text](url) when web search is used.
        text = response.output_text or ""
        return _build_result(response, text)

    return with_retries(_call)


def query_with_followup(question: str, followup: str) -> tuple[ProviderResult, ProviderResult]:
    """
    Two-turn conversation using the Responses API's previous_response_id chaining.

    Round 1: Ask the question (with web search).
    Round 2: Ask the follow-up in the same conversation context.
             OpenAI stores the history server-side — no tokens re-sent.
             Web search stays enabled on the follow-up turn too.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    def _call() -> tuple[ProviderResult, ProviderResult]:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        # Round 1
        response1 = client.responses.create(
            model=MODEL,
            tools=[{"type": WEB_SEARCH_TOOL_TYPE}],
            input=question,
        )
        text1 = response1.output_text or ""
        r1 = _build_result(response1, text1)

        if not text1.strip():
            return r1, ProviderResult(error="round1_empty")

        # Round 2 — chained via previous_response_id
        response2 = client.responses.create(
            model=MODEL,
            tools=[{"type": WEB_SEARCH_TOOL_TYPE}],
            input=followup,
            previous_response_id=response1.id,
        )
        text2 = response2.output_text or ""
        r2 = _build_result(response2, text2)

        return r1, r2

    return with_retries(_call)
