"""WebishProviderAdapter must surface structured citations/search results."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass

from api.adapters.provider_registry import WebishProviderAdapter
from api.domain.classifier import citation_urls


@dataclass
class _FakeCitation:
    url: str
    title: str | None = None
    source_rank: int | None = None

    def to_dict(self) -> dict:
        return {"url": self.url, "title": self.title, "source_rank": self.source_rank}


@dataclass
class _FakeSearchResult:
    url: str
    title: str | None = None
    result_rank: int | None = None

    def to_dict(self) -> dict:
        return {"url": self.url, "title": self.title, "result_rank": self.result_rank}


class _FakeResult:
    def __init__(self):
        self.response = "Acme is a strong option [1]."
        self.provider = "perplexity"
        self.model = "sonar"
        self.error = ""
        self.web_search_used = True
        self.search_queries = ["best crm"]
        self.citations = [_FakeCitation(url="https://g2.com/acme", title="Acme on G2", source_rank=1)]
        self.search_results = [_FakeSearchResult(url="https://reddit.com/r/crm/acme", result_rank=2)]

    def safe_usage_metadata(self):
        return {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}

    def safe_raw_metadata(self):
        return {"finish_reason": "stop"}


class ProviderRegistryTests(unittest.TestCase):
    def test_complete_surfaces_structured_citations(self):
        adapter = WebishProviderAdapter(provider_name="perplexity", query=lambda prompt: _FakeResult())
        response = asyncio.run(
            adapter.complete(prompt="best crm?", seed=1, temperature=0.7, top_p=1.0, idempotency_key="k")
        )

        self.assertEqual(response.raw_metadata["citations"][0]["url"], "https://g2.com/acme")
        self.assertEqual(response.raw_metadata["search_results"][0]["url"], "https://reddit.com/r/crm/acme")
        self.assertTrue(response.raw_metadata["web_search_used"])

        # citation_urls must recover the structured URLs from raw_metadata.
        urls = citation_urls(response.text, raw_metadata=response.raw_metadata)
        self.assertIn("https://g2.com/acme", urls)
        self.assertIn("https://reddit.com/r/crm/acme", urls)

    def test_complete_handles_missing_structured_fields(self):
        class _Bare:
            response = "no citations here"
            provider = "openai"
            model = "gpt"
            error = ""

            def safe_usage_metadata(self):
                return {}

            def safe_raw_metadata(self):
                return {}

        adapter = WebishProviderAdapter(provider_name="openai", query=lambda prompt: _Bare())
        response = asyncio.run(
            adapter.complete(prompt="x", seed=None, temperature=0.7, top_p=1.0, idempotency_key="k")
        )
        self.assertEqual(response.raw_metadata["citations"], [])
        self.assertEqual(response.raw_metadata["search_results"], [])


if __name__ == "__main__":
    unittest.main()
