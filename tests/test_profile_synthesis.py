"""AI-drafted profile fields: LLM parse + deterministic fallback (network-free)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from api.domain.ports import UpstreamProviderResponse
from api.question_gen.profile_synthesis import synthesize_profile_fields


class _FakeLLM:
    provider = "openrouter"
    model = "fake-model"

    def __init__(self, text=None, error=None):
        self._text = text
        self._error = error

    def complete(self, *, prompt, seed, temperature, idempotency_key):
        if self._error:
            raise self._error
        return UpstreamProviderResponse(text=self._text, provider="openrouter", model="fake-model")


ARTIFACTS = {"auto_extracted": {
    "tagline": "AI creative canvas",
    "about_copy": "Melius is a node-based multimodal content generation platform for creative teams.",
}}


class ProfileSynthesisTests(unittest.TestCase):
    def test_llm_object_is_parsed(self):
        payload = (
            '{"description": "Melius is an AI creative canvas for generating multimodal content.", '
            '"industry": "AI creative tools", '
            '"audiences": ["creative teams", "video artists"], '
            '"competitors": ["Runway", "Freepik"]}'
        )
        fields = synthesize_profile_fields(
            brand_name="Melius", crawl_artifacts=ARTIFACTS,
            provider=_FakeLLM(text=payload), existing_competitors=["Flora"],
        )
        self.assertEqual(fields.industry, "AI creative tools")
        self.assertIn("creative teams", fields.audiences)
        self.assertTrue(fields.description.startswith("Melius is an AI creative canvas"))
        # Existing competitor kept first, model suggestions appended, deduped.
        self.assertEqual(fields.competitors[0], "Flora")
        self.assertIn("Runway", fields.competitors)

    def test_failure_falls_back_from_site_text(self):
        fields = synthesize_profile_fields(
            brand_name="Melius", crawl_artifacts=ARTIFACTS,
            provider=_FakeLLM(error=RuntimeError("down")), existing_competitors=["Flora", "Runway"],
        )
        self.assertTrue(fields.description)  # built from about_copy
        self.assertIn("node-based", fields.description)
        self.assertEqual(fields.competitors, ["Flora", "Runway"])

    def test_local_provider_uses_fallback(self):
        provider = SimpleNamespace(provider="local", model="heuristic")
        fields = synthesize_profile_fields(
            brand_name="Melius", crawl_artifacts=ARTIFACTS, provider=provider,
        )
        self.assertEqual(fields.provider, "local")
        self.assertTrue(fields.description)

    def test_empty_output_falls_back(self):
        fields = synthesize_profile_fields(
            brand_name="Melius", crawl_artifacts=ARTIFACTS, provider=_FakeLLM(text="   "),
        )
        self.assertTrue(fields.description)

    def test_competitors_capped_and_deduped(self):
        payload = '{"description": "x y z", "industry": "i", "audiences": [], "competitors": ["Runway", "runway", "Freepik"]}'
        fields = synthesize_profile_fields(
            brand_name="Melius", crawl_artifacts=ARTIFACTS,
            provider=_FakeLLM(text=payload), existing_competitors=["Flora"],
        )
        self.assertEqual([c.casefold() for c in fields.competitors], ["flora", "runway", "freepik"])


if __name__ == "__main__":
    unittest.main()
