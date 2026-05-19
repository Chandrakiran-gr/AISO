import asyncio
import json
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Action, Base, Client, ClientContext, Conversation, Message, Scan, ScanResult, User
from api.routes.assistant import (
    ConversationCreate,
    MessageCreate,
    _assistant_context,
    _fallback_assistant_text,
    _llm_messages,
    create_conversation,
    get_conversation,
    list_conversations,
    stream_message,
)


class AssistantRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _seed(self):
        session = self.Session()
        session.add(User(id="user-1", email="founder@example.com"))
        session.add(User(id="user-2", email="other@example.com"))
        session.add(
            Client(
                id="client-1",
                user_id="user-1",
                name="AISO Demo",
                url="https://example.com",
                industry="AI search",
                location="Boston",
            )
        )
        session.add(
            Client(
                id="client-2",
                user_id="user-2",
                name="Other Demo",
                url="https://other.example",
            )
        )
        session.add(
            ClientContext(
                client_id="client-1",
                status="confirmed",
                profile_json=json.dumps(
                    {
                        "business": {"name": "AISO Demo"},
                        "offerings": [{"name": "Visibility audit"}],
                    }
                ),
                warnings_json=json.dumps([]),
            )
        )
        session.add(
            Scan(
                id="scan-1",
                client_id="client-1",
                status="complete",
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            ScanResult(
                id="result-1",
                scan_id="scan-1",
                client_id="client-1",
                provider="openai",
                group="G2",
                total_questions=10,
                mention_count=7,
            )
        )
        session.add(
            Action(
                id="action-1",
                client_id="client-1",
                scan_id="scan-1",
                title="Publish comparison page",
                description="Show why AISO is different from generic SEO tools.",
                priority="high",
                status="open",
                score=9.5,
                sort_order=1,
            )
        )
        session.commit()
        return session

    def test_create_and_get_conversation_persists_for_client_owner(self):
        session = self._seed()
        try:
            created = asyncio.run(
                create_conversation(
                    ConversationCreate(client_id="client-1"),
                    db=session,
                    user_id="user-1",
                )
            )
            self.assertEqual(created.client_id, "client-1")
            self.assertEqual(session.query(Conversation).count(), 1)

            conversations = asyncio.run(list_conversations("client-1", db=session, user_id="user-1"))
            self.assertEqual([conversation.id for conversation in conversations], [created.id])

            detail = asyncio.run(get_conversation(created.id, db=session, user_id="user-1"))
            self.assertEqual(detail.messages, [])
        finally:
            session.close()

    def test_conversation_access_is_user_scoped(self):
        session = self._seed()
        try:
            created = asyncio.run(
                create_conversation(
                    ConversationCreate(client_id="client-1"),
                    db=session,
                    user_id="user-1",
                )
            )
            with self.assertRaises(Exception):
                asyncio.run(get_conversation(created.id, db=session, user_id="user-2"))
        finally:
            session.close()

    def test_context_and_fallback_use_scan_and_actions(self):
        session = self._seed()
        try:
            created = asyncio.run(
                create_conversation(
                    ConversationCreate(client_id="client-1"),
                    db=session,
                    user_id="user-1",
                )
            )
            conversation = session.query(Conversation).filter(Conversation.id == created.id).one()
            context = _assistant_context(session, conversation)
            answer = _fallback_assistant_text(context, "what are my top action items?")

            self.assertIn("Publish comparison page", answer)
            self.assertIn("70.0/100", answer)
        finally:
            session.close()

    def test_llm_messages_do_not_duplicate_current_user_turn(self):
        context = {
            "history": [
                {"role": "assistant", "content": "What would you like to review?"},
                {"role": "user", "content": "What are my top action items?"},
            ]
        }
        messages = _llm_messages(context, "What are my top action items?")

        self.assertEqual(
            messages,
            [
                {"role": "assistant", "content": "What would you like to review?"},
                {"role": "user", "content": "What are my top action items?"},
            ],
        )

    def test_stream_message_redacts_pasted_api_keys_before_persistence(self):
        session = self._seed()
        try:
            created = asyncio.run(
                create_conversation(
                    ConversationCreate(client_id="client-1"),
                    db=session,
                    user_id="user-1",
                )
            )
            response = asyncio.run(
                stream_message(
                    created.id,
                    MessageCreate(content="Use sk-ant-" + "a" * 24 + " in the plan"),
                    db=session,
                    user_id="user-1",
                )
            )
            async def collect_body():
                parts: list[str] = []
                async for chunk in response.body_iterator:
                    parts.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
                return "".join(parts)

            body = asyncio.run(collect_body())
            self.assertIn("event: done", body)

            messages = session.query(Message).order_by(Message.created_at.asc()).all()
            self.assertEqual(messages[0].role, "user")
            self.assertIn("[redacted-api-key]", messages[0].content)
            self.assertNotIn("sk-ant-", messages[0].content)
            self.assertEqual(messages[1].role, "assistant")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
