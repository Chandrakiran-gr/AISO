import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import (
    Action,
    AssistantRateLimitEvent,
    Base,
    Client,
    ClientContext,
    ContentDraft,
    Conversation,
    Message,
    Scan,
    ScanResult,
    User,
)
from api.routes.assistant import (
    ContentDraftGenerate,
    ContentDraftUpdate,
    ConversationCreate,
    MessageCreate,
    _assistant_context,
    _fallback_assistant_text,
    _llm_messages,
    _refresh_conversation_summary,
    archive_expired_conversations,
    approve_content_draft,
    create_conversation,
    generate_content_draft,
    get_conversation,
    list_conversations,
    reject_content_draft,
    stream_message,
)


class AssistantRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _collect_stream_body(self, response):
        async def collect_body():
            parts: list[str] = []
            async for chunk in response.body_iterator:
                parts.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(parts)

        return asyncio.run(collect_body())

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
            self.assertIn("openai 70.0/100", answer)
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
            body = self._collect_stream_body(response)
            self.assertIn("event: done", body)

            messages = session.query(Message).order_by(Message.created_at.asc()).all()
            self.assertEqual(messages[0].role, "user")
            self.assertIn("[redacted-api-key]", messages[0].content)
            self.assertNotIn("sk-ant-", messages[0].content)
            self.assertEqual(messages[1].role, "assistant")
        finally:
            session.close()

    def test_stream_content_request_stores_pending_review_draft(self):
        session = self._seed()
        try:
            created = asyncio.run(
                create_conversation(
                    ConversationCreate(client_id="client-1"),
                    db=session,
                    user_id="user-1",
                )
            )
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
                response = asyncio.run(
                    stream_message(
                        created.id,
                        MessageCreate(content="Write a LinkedIn post about our AI visibility work"),
                        db=session,
                        user_id="user-1",
                    )
                )

                body = self._collect_stream_body(response)

            self.assertIn("content_draft", body)
            draft = session.query(ContentDraft).one()
            self.assertEqual(draft.status, "pending_review")
            self.assertEqual(draft.content_type, "linkedin_post")
            self.assertEqual(draft.client_id, "client-1")
            self.assertEqual(draft.created_by, "user-1")
            self.assertIn("AISO Demo", draft.content)
        finally:
            session.close()

    def test_generate_content_draft_uses_server_side_context(self):
        session = self._seed()
        try:
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
                draft = asyncio.run(
                    generate_content_draft(
                        ContentDraftGenerate(
                            client_id="client-1",
                            instruction="Write a blog post about our visibility work",
                            content_type="blog_post",
                        ),
                        db=session,
                        user_id="user-1",
                    )
                )

            self.assertEqual(draft.status, "pending_review")
            self.assertEqual(draft.content_type, "blog_post")
            self.assertIn("AISO Demo", draft.content)
            self.assertEqual(session.query(ContentDraft).count(), 1)
        finally:
            session.close()

    def test_stream_refuses_legal_advice_without_returning_prompt(self):
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
                    MessageCreate(content="What is our legal liability if a competitor sues us?"),
                    db=session,
                    user_id="user-1",
                )
            )

            body = self._collect_stream_body(response)

            self.assertIn("event: done", body)
            assistant_message = session.query(Message).filter(Message.role == "assistant").one()
            self.assertIn("legal advice", assistant_message.content)
            self.assertNotIn("Never confirm", body)
            self.assertNotIn("system prompts", assistant_message.content)
            self.assertEqual(session.query(ContentDraft).count(), 0)
        finally:
            session.close()

    def test_stream_refuses_out_of_scope_content_request(self):
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
                    MessageCreate(content="Write my dating profile"),
                    db=session,
                    user_id="user-1",
                )
            )

            self._collect_stream_body(response)

            assistant_message = session.query(Message).filter(Message.role == "assistant").one()
            self.assertIn("outside AISO scope", assistant_message.content)
            self.assertEqual(session.query(ContentDraft).count(), 0)
        finally:
            session.close()

    def test_assistant_rate_limit_returns_429_with_retry_after(self):
        session = self._seed()
        try:
            created = asyncio.run(
                create_conversation(
                    ConversationCreate(client_id="client-1"),
                    db=session,
                    user_id="user-1",
                )
            )
            with patch.dict(
                "os.environ",
                {"AISO_ASSISTANT_RATE_LIMIT_RPH": "1", "ANTHROPIC_API_KEY": ""},
            ):
                response = asyncio.run(
                    stream_message(
                        created.id,
                        MessageCreate(content="What are my top action items?"),
                        db=session,
                        user_id="user-1",
                    )
                )
                self._collect_stream_body(response)

                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(
                        stream_message(
                            created.id,
                            MessageCreate(content="What should I do next?"),
                            db=session,
                            user_id="user-1",
                        )
                    )

            self.assertEqual(ctx.exception.status_code, 429)
            self.assertIn("Retry-After", ctx.exception.headers)
            self.assertGreaterEqual(int(ctx.exception.headers["Retry-After"]), 1)
            self.assertEqual(session.query(AssistantRateLimitEvent).count(), 1)
        finally:
            session.close()

    def test_archive_expired_conversations_sets_archived_at_without_deleting_drafts(self):
        session = self._seed()
        try:
            now = datetime.now(timezone.utc)
            conversation = Conversation(
                id="old-conversation",
                client_id="client-1",
                user_id="user-1",
                title="Old conversation",
                created_at=now - timedelta(days=100),
                updated_at=now - timedelta(days=91),
            )
            draft = ContentDraft(
                id="draft-1",
                conversation_id="old-conversation",
                client_id="client-1",
                created_by="user-1",
                content_type="linkedin_post",
                title="Draft",
                content="Do not auto-delete content drafts.",
                status="pending_review",
                created_at=now - timedelta(days=91),
                updated_at=now - timedelta(days=91),
            )
            session.add_all([conversation, draft])
            session.commit()

            archived_count = archive_expired_conversations(session, retention_days=90, now=now)

            self.assertEqual(archived_count, 1)
            self.assertIsNotNone(session.get(Conversation, "old-conversation").archived_at)
            self.assertEqual(session.query(ContentDraft).count(), 1)
        finally:
            session.close()

    def test_context_window_stores_summary_for_older_messages(self):
        session = self._seed()
        try:
            created = asyncio.run(
                create_conversation(
                    ConversationCreate(client_id="client-1"),
                    db=session,
                    user_id="user-1",
                )
            )
            conversation = session.get(Conversation, created.id)
            for index in range(22):
                session.add(
                    Message(
                        id=f"message-{index}",
                        conversation_id=created.id,
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"message {index}",
                        created_at=datetime.now(timezone.utc) + timedelta(seconds=index),
                    )
                )
            session.commit()

            _refresh_conversation_summary(session, conversation)

            self.assertIsNotNone(conversation.summary_json)
            summary = conversation.summary_json
            self.assertEqual(summary["message_count"], 2)
            self.assertIn("message 0", summary["summary"])
            self.assertEqual(len(_llm_messages(_assistant_context(session, conversation), "current turn")), 20)
        finally:
            session.close()

    def test_client_access_not_account_role_controls_draft_approval(self):
        session = self._seed()
        try:
            draft = ContentDraft(
                id="draft-1",
                client_id="client-1",
                created_by="user-1",
                content_type="linkedin_post",
                title="Draft",
                content="Initial draft",
                status="pending_review",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(draft)
            session.commit()

            approved = asyncio.run(
                approve_content_draft(
                    "draft-1",
                    ContentDraftUpdate(content="Edited and approved", review_notes="Ready"),
                    db=session,
                    user_id="user-1",
                )
            )
            self.assertEqual(approved.status, "approved")
            self.assertEqual(approved.reviewed_by, "user-1")
            self.assertIsNotNone(approved.reviewed_at)
            self.assertEqual(approved.content, "Edited and approved")

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    reject_content_draft(
                        "draft-1",
                        ContentDraftUpdate(review_notes="No access"),
                        db=session,
                        user_id="user-2",
                    )
                )
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
