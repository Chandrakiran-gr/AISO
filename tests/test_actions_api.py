import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Action, Base, Client, Scan, User
from api.routes.actions import list_actions, update_action, ActionUpdate


class ActionsApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_list_actions_defaults_to_latest_scan_and_status_filter(self):
        session = self.Session()
        now = datetime.now(timezone.utc)
        try:
            session.add(User(id="user-1", email="founder@example.com"))
            session.add(Client(id="client-1", user_id="user-1", name="AISO Demo", url="https://example.com"))
            session.add_all(
                [
                    Scan(id="old-scan", client_id="client-1", status="complete", created_at=now - timedelta(days=1)),
                    Scan(id="new-scan", client_id="client-1", status="complete", created_at=now),
                ]
            )
            session.add_all(
                [
                    Action(
                        id="old-action",
                        client_id="client-1",
                        scan_id="old-scan",
                        action_key="old",
                        title="Old action",
                        status="open",
                        score=99,
                        sort_order=1,
                    ),
                    Action(
                        id="new-action-2",
                        client_id="client-1",
                        scan_id="new-scan",
                        action_key="new-2",
                        title="Second new action",
                        status="done",
                        score=60,
                        sort_order=2,
                    ),
                    Action(
                        id="new-action-1",
                        client_id="client-1",
                        scan_id="new-scan",
                        action_key="new-1",
                        title="First new action",
                        status="open",
                        score=80,
                        sort_order=1,
                        evidence_json={"kind": "test"},
                    ),
                ]
            )
            session.commit()

            latest = asyncio.run(
                list_actions(
                    "client-1",
                    db=session,
                    user_id="user-1",
                )
            )
            open_only = asyncio.run(
                list_actions(
                    "client-1",
                    status="open",
                    db=session,
                    user_id="user-1",
                )
            )

            self.assertEqual([action.id for action in latest], ["new-action-1", "new-action-2"])
            self.assertEqual([action.id for action in open_only], ["new-action-1"])
        finally:
            session.close()

    def test_update_action_is_user_scoped_and_validates_status(self):
        session = self.Session()
        try:
            session.add(User(id="user-1", email="founder@example.com"))
            session.add(User(id="user-2", email="other@example.com"))
            session.add(Client(id="client-1", user_id="user-1", name="AISO Demo", url="https://example.com"))
            session.add(Action(id="action-1", client_id="client-1", title="Review", status="open"))
            session.commit()

            updated = asyncio.run(
                update_action(
                    "client-1",
                    "action-1",
                    ActionUpdate(status="done"),
                    db=session,
                    user_id="user-1",
                )
            )

            self.assertEqual(updated.status, "done")
            self.assertIsNotNone(updated.completed_at)

            with self.assertRaises(HTTPException):
                asyncio.run(
                    update_action(
                        "client-1",
                        "action-1",
                        ActionUpdate(status="open"),
                        db=session,
                        user_id="user-2",
                    )
                )
        finally:
            session.close()

    def test_list_actions_does_not_fall_back_to_stale_scan_actions(self):
        session = self.Session()
        now = datetime.now(timezone.utc)
        try:
            session.add(User(id="user-1", email="founder@example.com"))
            session.add(Client(id="client-1", user_id="user-1", name="AISO Demo", url="https://example.com"))
            session.add_all(
                [
                    Scan(id="old-scan", client_id="client-1", status="complete", created_at=now - timedelta(days=1)),
                    Scan(id="new-scan", client_id="client-1", status="complete", created_at=now),
                ]
            )
            session.add(
                Action(
                    id="old-action",
                    client_id="client-1",
                    scan_id="old-scan",
                    title="Old action",
                    status="open",
                )
            )
            session.commit()

            actions = asyncio.run(
                list_actions(
                    "client-1",
                    db=session,
                    user_id="user-1",
                )
            )

            self.assertEqual(actions, [])
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
