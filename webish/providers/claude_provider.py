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
from webish.providers.base import ProviderResult, with_retries

MODEL = "claude-haiku-4-5-20251001"  # current Haiku (fastest, cheapest Anthropic)
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

        return ProviderResult(response=text)

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
        r1 = ProviderResult(response=text1)

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
        r2 = ProviderResult(response=text2)

        return r1, r2

    return with_retries(_call)

