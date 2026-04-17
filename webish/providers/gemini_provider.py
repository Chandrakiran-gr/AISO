"""
Google Gemini provider.
Uses the google.generativeai SDK (officially deprecated but still functional).
Generates content using Gemini model.
"""
import os
from webish.providers.base import ProviderResult, with_retries

MODEL = "gemini-2.5-flash"


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


def query(question: str) -> ProviderResult:
    """Query Google Gemini and return response."""
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY is not set.")

    def _call() -> ProviderResult:
        from google.generativeai.client import configure
        from google.generativeai.generative_models import GenerativeModel
        
        configure(api_key=api_key)
        model = GenerativeModel(MODEL)
        response = model.generate_content(question)
        text = response.text or ""

        # Return response (citations would appear in the text if included by the model)
        return ProviderResult(response=text)

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
        from google.generativeai.client import configure
        from google.generativeai.generative_models import GenerativeModel

        configure(api_key=api_key)
        model = GenerativeModel(MODEL)
        chat = model.start_chat()

        # Round 1
        response1 = chat.send_message(question)
        text1 = response1.text or ""
        r1 = ProviderResult(response=text1)

        if not text1.strip():
            return r1, ProviderResult(error="round1_empty")

        # Round 2 — same chat session (context preserved)
        response2 = chat.send_message(followup)
        text2 = response2.text or ""
        r2 = ProviderResult(response=text2)

        return r1, r2

    return with_retries(_call)

