"""Contract test for GET /api/v1/auth/me (per-user entitlements for the frontend)."""

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth import get_current_user_id
from api.database import Base, Client, User, get_db
from api.main import app


class AuthMeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        db = self.Session()
        db.add(User(id="free-u", email="f@e.com", plan_tier="free"))
        db.add(User(id="pro-u", email="p@e.com", plan_tier="pro"))
        db.add(User(id="cust-u", email="c@e.com", plan_tier="custom"))
        db.add(Client(id="c1", user_id="cust-u", name="B1", url="http://x"))
        db.add(Client(id="c2", user_id="cust-u", name="B2", url="http://y"))
        db.commit()
        db.close()

        def override_db():
            d = self.Session()
            try:
                yield d
            finally:
                d.close()

        self._uid = "free-u"
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user_id] = lambda: self._uid
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_id, None)
        self.engine.dispose()

    def _me(self, uid):
        self._uid = uid
        return self.client.get("/api/v1/auth/me")

    def test_free_user(self):
        r = self._me("free-u")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["plan_tier"], "free")
        self.assertEqual(d["max_clients"], 1)
        self.assertFalse(d["uses_managed_keys"])
        self.assertEqual(d["business_count"], 0)
        self.assertEqual(d["billing_model"], "none")
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")

    def test_pro_user(self):
        d = self._me("pro-u").json()
        self.assertEqual(d["plan_tier"], "pro")
        self.assertEqual(d["max_clients"], 1)
        self.assertTrue(d["uses_managed_keys"])
        self.assertEqual(d["billing_model"], "flat")

    def test_custom_user_counts_businesses(self):
        d = self._me("cust-u").json()
        self.assertEqual(d["plan_tier"], "custom")
        self.assertIsNone(d["max_clients"])
        self.assertTrue(d["uses_managed_keys"])
        self.assertEqual(d["business_count"], 2)
        self.assertEqual(d["billing_model"], "per_seat")

    def test_unknown_user_is_401(self):
        self.assertEqual(self._me("ghost").status_code, 401)


if __name__ == "__main__":
    unittest.main()
