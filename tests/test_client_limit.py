"""Per-user business-creation limit (app-level pre-check; SQLite has no trigger).

free/pro = 1 business, custom = unlimited. Updating an existing business is not
counted as creating a new one.
"""

import asyncio
import unittest

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.client_limits import is_client_limit_violation
from api.database import Base, Client, User
from api.routes.clients import ClientCreate, create_client


class ClientLimitTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _create(self, user_id, name, client_id=None):
        payload = ClientCreate(id=client_id, name=name)
        return asyncio.run(create_client(payload, Response(), db=self.db, user_id=user_id))

    def _count(self, user_id):
        return self.db.query(Client).filter(Client.user_id == user_id).count()

    def test_free_user_second_create_reuses_single_business(self):
        # Free/pro have exactly one business: a second create (no id) reuses it
        # in place rather than spawning a duplicate or 403-ing the user. The
        # one-business limit is now enforced by reuse, not rejection.
        self.db.add(User(id="free-u", email="f@e.com", plan_tier="free"))
        self.db.commit()
        self._create("free-u", "Biz One")
        first_id = self.db.query(Client).filter(Client.user_id == "free-u").one().id
        self._create("free-u", "Biz Two")
        self.assertEqual(self._count("free-u"), 1)
        only = self.db.query(Client).filter(Client.user_id == "free-u").one()
        self.assertEqual(only.id, first_id)
        self.assertEqual(only.name, "Biz Two")

    def test_pro_user_second_create_reuses_single_business(self):
        self.db.add(User(id="pro-u", email="p@e.com", plan_tier="pro"))
        self.db.commit()
        self._create("pro-u", "Biz One")
        self._create("pro-u", "Biz Two")
        self.assertEqual(self._count("pro-u"), 1)

    def test_custom_user_unlimited(self):
        self.db.add(User(id="cust-u", email="c@e.com", plan_tier="custom"))
        self.db.commit()
        for name in ("One", "Two", "Three"):
            self._create("cust-u", name)
        self.assertEqual(self._count("cust-u"), 3)

    def test_updating_existing_business_not_blocked(self):
        self.db.add(User(id="free-u", email="f@e.com", plan_tier="free"))
        self.db.commit()
        self._create("free-u", "Biz One")
        existing_id = self.db.query(Client).filter(Client.user_id == "free-u").first().id
        # Re-POST with the same id is an update, not a new business — must succeed.
        self._create("free-u", "Renamed", client_id=existing_id)
        self.assertEqual(self._count("free-u"), 1)
        self.assertEqual(
            self.db.query(Client).filter(Client.id == existing_id).first().name, "Renamed"
        )


class ViolationDetectionTests(unittest.TestCase):
    def test_detects_pgcode(self):
        exc = Exception("boom")
        setattr(exc, "pgcode", "P0LIM")
        self.assertTrue(is_client_limit_violation(exc))

    def test_detects_message_on_orig(self):
        inner = Exception("ERROR: client_business_limit_exceeded for user x")
        outer = Exception("wrapped")
        setattr(outer, "orig", inner)
        self.assertTrue(is_client_limit_violation(outer))

    def test_ignores_unrelated_error(self):
        self.assertFalse(is_client_limit_violation(Exception("some other db error")))


if __name__ == "__main__":
    unittest.main()
