"""Review-prompt generation: LLM parse/split + deterministic fallback.

Network-free: a fake pass-through provider returns canned text, so parsing and
classification are exercised deterministically. The fallback path uses no LLM.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from api.domain.ports import BusinessProfileSnapshot, UpstreamProviderResponse
from api.question_gen.review import generate_review_prompts


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


def _snapshot(competitors=("Intercom", "Zendesk")):
    return BusinessProfileSnapshot(
        client_id="client-1",
        vertical="b2b_saas",
        objective="consideration",
        category="customer engagement platform",
        icp={"firmographics": {"industry": "SaaS", "employee_band": "50-500"}},
        geographic_scope={"countries": ["United States"]},
        competitors=list(competitors),
        personas={"primary": "head of customer support"},
        floor_met=True,
    )


class ReviewPromptTests(unittest.TestCase):
    def setUp(self):
        self.client = SimpleNamespace(name="Melius")

    def test_llm_object_form_is_parsed_and_classified(self):
        payload = (
            '{"branded": ["Melius reviews from support leaders", '
            '"Melius vs Intercom pricing"], '
            '"category": ["best customer engagement platform for startups", '
            '"how much does a customer engagement platform cost"]}'
        )
        result = generate_review_prompts(
            client=self.client, snapshot=_snapshot(), provider=_FakeLLM(text=payload),
        )
        by_text = {p.text: p for p in result.prompts}
        self.assertEqual(len(result.prompts), 4)

        reviews = by_text["Melius reviews from support leaders"]
        self.assertEqual(reviews.kind, "branded")
        self.assertEqual(reviews.brand_frame, "brand_only")
        self.assertEqual(reviews.journey_stage, "J5")  # "reviews" -> trust stage

        vs = by_text["Melius vs Intercom pricing"]
        self.assertEqual(vs.kind, "branded")
        self.assertEqual(vs.brand_frame, "branded_comparison")  # names a competitor
        self.assertEqual(vs.journey_stage, "J4")  # "pricing" -> transactional

        cat = by_text["best customer engagement platform for startups"]
        self.assertEqual(cat.kind, "category")
        self.assertEqual(cat.brand_frame, "unbranded_category")
        self.assertEqual(cat.journey_stage, "J1")  # "best" -> discovery

    def test_llm_flat_array_form_is_parsed(self):
        payload = (
            '[{"question": "Melius pricing plans", "brand_frame": "brand_only"}, '
            '{"question": "best crm tools", "brand_frame": "unbranded_category"}]'
        )
        result = generate_review_prompts(
            client=self.client, snapshot=_snapshot(), provider=_FakeLLM(text=payload),
        )
        kinds = sorted(p.kind for p in result.prompts)
        self.assertEqual(kinds, ["branded", "category"])

    def test_llm_failure_falls_back_deterministically(self):
        result = generate_review_prompts(
            client=self.client, snapshot=_snapshot(),
            provider=_FakeLLM(error=RuntimeError("all models rate-limited")),
            final_count=15,
        )
        self.assertGreater(len(result.prompts), 0)
        self.assertTrue(all(p.text.endswith("?") for p in result.prompts))

    def test_empty_llm_output_falls_back(self):
        result = generate_review_prompts(
            client=self.client, snapshot=_snapshot(), provider=_FakeLLM(text="   "),
            final_count=12,
        )
        self.assertGreater(len(result.prompts), 0)

    def test_local_provider_uses_fallback_without_calling_llm(self):
        provider = SimpleNamespace(provider="local", model="heuristic-v1")
        result = generate_review_prompts(
            client=self.client, snapshot=_snapshot(), provider=provider, final_count=18,
        )
        self.assertEqual(result.provider, "local")
        self.assertGreater(len(result.prompts), 0)

    def test_no_competitors_produces_no_comparison_prompts(self):
        provider = SimpleNamespace(provider="local", model="heuristic-v1")
        result = generate_review_prompts(
            client=self.client, snapshot=_snapshot(competitors=()), provider=provider,
            final_count=30,
        )
        for prompt in result.prompts:
            lowered = prompt.text.lower()
            self.assertNotIn(" vs ", lowered)
            self.assertNotIn("alternatives to", lowered)
            self.assertNotEqual(prompt.brand_frame, "competitor_only")

    def test_prompts_carry_valid_stage_and_frame(self):
        payload = '{"branded": ["Melius demo"], "category": ["top crm software"]}'
        result = generate_review_prompts(
            client=self.client, snapshot=_snapshot(), provider=_FakeLLM(text=payload),
        )
        valid_stages = {"J1", "J2", "J3", "J4", "J5", "J6"}
        valid_frames = {"unbranded_category", "brand_only", "branded_comparison", "competitor_only"}
        for prompt in result.prompts:
            self.assertIn(prompt.journey_stage, valid_stages)
            self.assertIn(prompt.brand_frame, valid_frames)


if __name__ == "__main__":
    unittest.main()
