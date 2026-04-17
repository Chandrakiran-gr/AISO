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
from webish.providers.base import ProviderResult, with_retries

MODEL = "gpt-4o-mini"


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
            tools=[{"type": "web_search_preview"}],  # web search always on
            input=question,
        )

        # output_text is a convenience property returning the final text response.
        # OpenAI embeds citation links inline as [text](url) when web search is used.
        text = response.output_text or ""
        return ProviderResult(response=text)

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
            tools=[{"type": "web_search_preview"}],
            input=question,
        )
        text1 = response1.output_text or ""
        r1 = ProviderResult(response=text1)

        if not text1.strip():
            return r1, ProviderResult(error="round1_empty")

        # Round 2 — chained via previous_response_id
        response2 = client.responses.create(
            model=MODEL,
            tools=[{"type": "web_search_preview"}],
            input=followup,
            previous_response_id=response1.id,
        )
        text2 = response2.output_text or ""
        r2 = ProviderResult(response=text2)

        return r1, r2

    return with_retries(_call)

