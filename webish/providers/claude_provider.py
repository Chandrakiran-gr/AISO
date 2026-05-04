"""
Anthropic Claude provider with native web search enabled.

Uses Anthropic's built-in web_search_20250305 tool, which matches the
"Web search" toggle visible in Claude.ai — this is the same capability,
exposed through the API.

Claude performs searches autonomously during the response (up to max_uses),
then writes its final answer with inline citations. We extract all text blocks
from the response (tool_use blocks are intermediate steps and not needed).

Note: max_uses=5 means Claude can perform up to 5 web searches per question.
This is configurable — increase for complex multi-part questions.
"""
import os
from typing import Any
from webish.providers.base import ProviderCitation, ProviderResult, ProviderSearchResult, with_retries

MODEL = os.environ.get("AISO_CLAUDE_MODEL", "claude-haiku-4-5-20251001")  # current Haiku (fastest, cheapest Anthropic)
MAX_TOKENS = 2048   # higher than pure-chat because tool use adds overhead
MAX_SEARCHES = 2    # ↓ from 5: each search adds ~10-15s latency — 2 is enough for local business queries

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to real-time web search. "
    "When you reference businesses, websites, or sources, format them as "
    "inline markdown links: [Business Name or page title](https://url.com). "
    "Use numbered lists for recommendations."
)

WEB_SEARCH_TOOL: Any = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": MAX_SEARCHES,
}


def _dump_message(message: Any) -> dict[str, Any]:
    if hasattr(message, "model_dump"):
        try:
            data = message.model_dump()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    if isinstance(message, dict):
        return message
    return {}


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _extract_evidence(data: dict[str, Any]) -> tuple[list[ProviderCitation], list[ProviderSearchResult], list[str], dict[str, Any], bool]:
    citations: list[ProviderCitation] = []
    search_results: list[ProviderSearchResult] = []
    search_queries: list[str] = []
    usage_metadata = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    web_search_used = False
    seen_citations: set[str] = set()
    seen_results: set[str] = set()

    for node in _walk(data):
        node_type = str(node.get("type") or "")
        if "web_search" in node_type or "web_search" in str(node.get("name") or ""):
            web_search_used = True
        if node.get("query"):
            query = str(node.get("query")).strip()
            if query and query not in search_queries:
                search_queries.append(query)

        url = str(node.get("url") or node.get("uri") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        title = str(node.get("title") or node.get("name") or "").strip() or None
        snippet = str(node.get("snippet") or node.get("cited_text") or node.get("text") or "").strip() or None
        if "citation" in node_type:
            if url not in seen_citations:
                seen_citations.add(url)
                citations.append(
                    ProviderCitation(
                        url=url,
                        title=title,
                        cited_text=snippet,
                        source_rank=len(citations) + 1,
                        origin="native_citation",
                        raw_metadata=node,
                    )
                )
        elif "web_search" in node_type or "result" in node_type or node.get("snippet"):
            if url not in seen_results:
                seen_results.add(url)
                search_results.append(
                    ProviderSearchResult(
                        url=url,
                        title=title,
                        snippet=snippet,
                        query=search_queries[-1] if search_queries else None,
                        result_rank=len(search_results) + 1,
                        raw_metadata=node,
                    )
                )

    server_tool_use = usage_metadata.get("server_tool_use") if isinstance(usage_metadata, dict) else None
    if isinstance(server_tool_use, dict) and server_tool_use.get("web_search_requests"):
        web_search_used = True
    return citations, search_results, search_queries, usage_metadata if isinstance(usage_metadata, dict) else {}, web_search_used or bool(citations or search_results)


def _build_result(message: Any, text: str) -> ProviderResult:
    raw_metadata = _dump_message(message)
    citations, search_results, search_queries, usage_metadata, web_search_used = _extract_evidence(raw_metadata)
    return ProviderResult(
        response=text,
        provider="claude",
        model=MODEL,
        web_search_used=web_search_used,
        search_queries=search_queries,
        citations=citations,
        search_results=search_results,
        usage_metadata=usage_metadata,
        raw_metadata=raw_metadata,
    )


def query(question: str) -> ProviderResult:
    """Query Claude with native web search enabled."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    def _call() -> ProviderResult:
        import anthropic
        from anthropic.types import TextBlock
        
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": question}],
        )

        # Response content is a list of blocks:
        #   - tool_use blocks  → Claude's search queries (intermediate, skip)
        #   - tool_result blocks → raw search results   (intermediate, skip)
        #   - text blocks      → Claude's written answer (this is what we want)
        text_parts = [
            block.text
            for block in message.content
            if isinstance(block, TextBlock)
        ]
        text = "\n\n".join(text_parts)

        return _build_result(message, text)

    return with_retries(_call)


def query_with_followup(question: str, followup: str) -> tuple[ProviderResult, ProviderResult]:
    """
    Two-turn conversation via Claude's messages array.

    Round 1: user asks the question.
    Round 2: append assistant response + user follow-up to messages array.
    Web search stays enabled on both turns.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    def _call() -> tuple[ProviderResult, ProviderResult]:
        import anthropic
        from anthropic.types import TextBlock

        client = anthropic.Anthropic(api_key=api_key)

        # Round 1
        messages_r1 = [{"role": "user", "content": question}]
        msg1 = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL],
            messages=messages_r1,
        )
        text1_parts = [
            block.text for block in msg1.content
            if isinstance(block, TextBlock)
        ]
        text1 = "\n\n".join(text1_parts)
        r1 = _build_result(msg1, text1)

        if not text1.strip():
            return r1, ProviderResult(error="round1_empty")

        # Round 2 — append assistant response + follow-up
        messages_r2 = [
            {"role": "user", "content": question},
            {"role": "assistant", "content": text1},
            {"role": "user", "content": followup},
        ]
        msg2 = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL],
            messages=messages_r2,
        )
        text2_parts = [
            block.text for block in msg2.content
            if isinstance(block, TextBlock)
        ]
        text2 = "\n\n".join(text2_parts)
        r2 = _build_result(msg2, text2)

        return r1, r2

    return with_retries(_call)
