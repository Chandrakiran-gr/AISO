"""Onboarding LLM provider selection by tier.

Onboarding *generation* runs on OpenRouter free/open models for every tier - it
is server-key text the user confirms, at ~zero cost, and is not the scan. So free
tier uses OpenRouter when configured, and only falls back to the deterministic
heuristic otherwise - never a paid first-party key. Pro/custom get the full
managed chain (OpenRouter, then a first-party key, then heuristic).
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from tests._pgharness import make_test_engine, reset_schema

from api.adapters.openai_chat import OpenAIChatAdapter
from api.adapters.profile_draft import (
    HeuristicProfileDraftAdapter,
    heuristic_profile_draft_provider,
    managed_profile_draft_provider,
)
from api.adapters.question_generation import managed_question_generation_provider
from api.adapters.question_scorer import managed_question_scorer_provider
from api.adapters.realism_filter import managed_realism_filter_provider
from api.database import User
from api.routes.onboarding import (
    get_profile_draft_provider,
    get_question_generation_provider,
)


class OpenAIChatAdapterTests(unittest.TestCase):
    @patch("api.adapters.openai_chat.requests.post")
    def test_complete_parses_message_content(self, mock_post):
        mock_post.return_value = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "id": "cmpl-1",
                "model": "gpt-4o-2024-08-06",
                "choices": [{"message": {"content": '  {"ok": true}  '}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 5},
            },
        )
        adapter = OpenAIChatAdapter(purpose="profile drafting", max_tokens=1800, api_key="sk-test")
        resp = adapter.complete(prompt="hi", seed=7, temperature=0.0, idempotency_key="k")

        self.assertEqual(resp.text, '{"ok": true}')
        self.assertEqual(resp.provider, "openai")
        self.assertEqual(resp.model, "gpt-4o-2024-08-06")
        self.assertEqual(resp.raw_metadata["seed"], 7)

        _args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["model"], adapter.model)
        self.assertEqual(kwargs["json"]["max_tokens"], 1800)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")

    def test_complete_without_key_raises(self):
        # Pin env: api_key="" otherwise falls back to an ambient OPENAI_API_KEY.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            adapter = OpenAIChatAdapter(purpose="profile drafting", max_tokens=10, api_key="")
            with self.assertRaises(RuntimeError):
                adapter.complete(prompt="hi", seed=1, temperature=0.0, idempotency_key="k")

    def test_available_reflects_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            self.assertTrue(OpenAIChatAdapter(purpose="x", max_tokens=1, api_key="sk").available())
            self.assertFalse(OpenAIChatAdapter(purpose="x", max_tokens=1, api_key="").available())


class ManagedProviderFactoryTests(unittest.TestCase):
    _ALL_MANAGED = (
        managed_profile_draft_provider,
        managed_question_generation_provider,
        managed_question_scorer_provider,
        managed_realism_filter_provider,
    )

    def test_managed_prefers_openrouter_when_keyed(self):
        # Every managed onboarding step runs on OpenRouter (free/open models) when
        # its key is present, so onboarding never spends a paid first-party key -
        # even when an OpenAI key is also configured.
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test", "OPENAI_API_KEY": "sk-test"}):
            for factory in self._ALL_MANAGED:
                self.assertEqual(factory().provider, "openrouter")

    def test_managed_falls_back_to_openai_without_openrouter(self):
        # No OpenRouter key but an OpenAI key -> OpenAI for every managed step.
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            os.environ.pop("OPENROUTER_API_KEY", None)
            os.environ.pop("ONBOARDING_LLM_API_KEY", None)
            for factory in self._ALL_MANAGED:
                self.assertEqual(factory().provider, "openai")

    def test_managed_falls_back_to_heuristic_when_unkeyed(self):
        with patch.dict(os.environ, {}, clear=False):
            for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ONBOARDING_LLM_API_KEY"):
                os.environ.pop(var, None)
            self.assertEqual(managed_profile_draft_provider().provider, "local")

    def test_heuristic_factory_returns_local(self):
        self.assertIsInstance(heuristic_profile_draft_provider(), HeuristicProfileDraftAdapter)
        self.assertEqual(heuristic_profile_draft_provider().provider, "local")


class TierSelectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = make_test_engine()  # Postgres when TEST_DATABASE_URL set, else SQLite
        reset_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(User(id="free-u", email="free@example.com", plan_tier="free"))
        self.db.add(User(id="pro-u", email="pro@example.com", plan_tier="pro"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_free_user_gets_openrouter_when_keyed(self):
        # Onboarding generation runs on OpenRouter free/open models for every tier
        # (server-key text the user confirms, ~zero cost). Free tier included.
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test"}):
            prov = get_profile_draft_provider(db=self.db, user_id="free-u")
        self.assertEqual(prov.provider, "openrouter")

    def test_free_user_never_uses_paid_first_party_key(self):
        # No OpenRouter, only a paid OpenAI key -> free tier stays on the heuristic,
        # never a paid first-party provider.
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            os.environ.pop("OPENROUTER_API_KEY", None)
            os.environ.pop("ONBOARDING_LLM_API_KEY", None)
            prov = get_profile_draft_provider(db=self.db, user_id="free-u")
        self.assertEqual(prov.provider, "local")  # free never spends a paid key

    def test_pro_user_gets_openrouter_when_keyed(self):
        # Pro users get OpenRouter for prompt generation when keyed.
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test"}):
            prov = get_question_generation_provider(db=self.db, user_id="pro-u")
        self.assertEqual(prov.provider, "openrouter")

    def test_pro_user_falls_back_to_openai_without_openrouter(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            os.environ.pop("OPENROUTER_API_KEY", None)
            os.environ.pop("ONBOARDING_LLM_API_KEY", None)
            prov = get_question_generation_provider(db=self.db, user_id="pro-u")
        self.assertEqual(prov.provider, "openai")

    def test_pro_user_falls_back_to_heuristic_when_unkeyed(self):
        with patch.dict(os.environ, {}, clear=False):
            for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ONBOARDING_LLM_API_KEY"):
                os.environ.pop(var, None)
            prov = get_profile_draft_provider(db=self.db, user_id="pro-u")
        self.assertEqual(prov.provider, "local")

    def test_unknown_user_defaults_to_managed(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test"}):
            prov = get_profile_draft_provider(db=self.db, user_id="ghost")
        self.assertEqual(prov.provider, "openrouter")  # managed, not heuristic


if __name__ == "__main__":
    unittest.main()
