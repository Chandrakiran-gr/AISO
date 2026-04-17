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
from webish.providers.base import ProviderResult, with_retries

MODEL = "sonar"
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
        if hasattr(response, "model_extra") and response.model_extra:
            citations = response.model_extra.get("citations") or []

        formatted = _inline_citations(text, citations)
        return ProviderResult(response=formatted)

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
        if hasattr(resp1, "model_extra") and resp1.model_extra:
            citations1 = resp1.model_extra.get("citations") or []
        formatted1 = _inline_citations(text1, citations1)
        r1 = ProviderResult(response=formatted1)

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
        if hasattr(resp2, "model_extra") and resp2.model_extra:
            citations2 = resp2.model_extra.get("citations") or []
        formatted2 = _inline_citations(text2, citations2)
        r2 = ProviderResult(response=formatted2)

        return r1, r2

    return with_retries(_call)

