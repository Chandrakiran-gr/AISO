"""Onboarding LLM provider selection by tier.

Free → deterministic heuristic (no server spend); pro/custom → managed OpenAI
(falling back to heuristic when no server key is configured).
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
from api.database import Base, User
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
    def test_managed_uses_openai_when_keyed(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            for factory in (
                managed_profile_draft_provider,
                managed_question_generation_provider,
                managed_question_scorer_provider,
                managed_realism_filter_provider,
            ):
                self.assertEqual(factory().provider, "openai")

    def test_managed_falls_back_to_heuristic_when_unkeyed(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
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

    def test_free_user_gets_heuristic_even_with_server_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            prov = get_profile_draft_provider(db=self.db, user_id="free-u")
        self.assertEqual(prov.provider, "local")  # free never spends server keys

    def test_pro_user_gets_openai_when_keyed(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            prov = get_question_generation_provider(db=self.db, user_id="pro-u")
        self.assertEqual(prov.provider, "openai")

    def test_pro_user_falls_back_to_heuristic_when_unkeyed(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            prov = get_profile_draft_provider(db=self.db, user_id="pro-u")
        self.assertEqual(prov.provider, "local")

    def test_unknown_user_defaults_to_managed(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            prov = get_profile_draft_provider(db=self.db, user_id="ghost")
        self.assertEqual(prov.provider, "openai")


if __name__ == "__main__":
    unittest.main()
