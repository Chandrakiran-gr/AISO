"""One-profile-per-business identity + upsert-by-identity (P1)."""

import asyncio
import unittest

from fastapi import Response
from sqlalchemy.orm import sessionmaker

from api.client_identity import business_url_key, canonical_business_url, resolve_user_business
from api.database import Client, User
from api.routes.clients import ClientCreate, create_client
from tests._pgharness import make_test_engine, reset_schema


class BusinessUrlKeyTests(unittest.TestCase):
    def test_scheme_www_trailing_slash_insensitive(self):
        key = "pemspa.com"
        self.assertEqual(business_url_key("https://www.pemspa.com/"), key)
        self.assertEqual(business_url_key("http://pemspa.com"), key)
        self.assertEqual(business_url_key("https://PEMSPA.com"), key)
        self.assertEqual(business_url_key("https://www.pemspa.com/?utm_source=x"), key)

    def test_path_preserved(self):
        self.assertEqual(business_url_key("https://x.com/a/b/"), "x.com/a/b")

    def test_empty(self):
        self.assertEqual(business_url_key(""), "")
        self.assertEqual(business_url_key(None), "")

    def test_canonical_url_normalizes_but_keeps_host(self):
        # Stored url stays a valid seed (host/scheme preserved), just normalized.
        self.assertEqual(canonical_business_url("https://www.pemspa.com/?utm_source=x"), "https://www.pemspa.com/")


class _DB(unittest.TestCase):
    """SQLite by default; real Postgres (FK-enforced) when TEST_DATABASE_URL is set."""

    def setUp(self):
        self.engine = make_test_engine()
        reset_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()


class ResolveUserBusinessTests(_DB):
    def _user(self, uid, tier):
        u = User(id=uid, email=f"{uid}@e.com", plan_tier=tier)
        self.db.add(u)
        self.db.commit()
        return u

    def test_resolves_by_owned_client_id(self):
        u = self._user("u1", "free")
        self.db.add(Client(id="c1", user_id="u1", name="P", url="https://pemspa.com"))
        self.db.commit()
        got = resolve_user_business(self.db, u, client_id="c1", url="https://anything.com")
        self.assertEqual(got.id, "c1")

    def test_resolves_by_url_key_when_no_id(self):
        u = self._user("u1", "custom")
        self.db.add(Client(id="c1", user_id="u1", name="P", url="https://www.pemspa.com/"))
        self.db.commit()
        got = resolve_user_business(self.db, u, client_id=None, url="http://pemspa.com")
        self.assertEqual(got.id, "c1")  # www/scheme variant still matches

    def test_free_user_reuses_single_business_even_on_url_change(self):
        u = self._user("u1", "free")
        self.db.add(Client(id="c1", user_id="u1", name="Old", url="https://old.com"))
        self.db.commit()
        got = resolve_user_business(self.db, u, client_id=None, url="https://brand-new-url.com")
        self.assertEqual(got.id, "c1")  # free/pro never spawn a second profile

    def test_custom_no_match_returns_none(self):
        u = self._user("u1", "custom")
        self.db.add(Client(id="c1", user_id="u1", name="A", url="https://a.com"))
        self.db.commit()
        self.assertIsNone(resolve_user_business(self.db, u, client_id=None, url="https://b.com"))

    def test_no_clients_returns_none(self):
        u = self._user("u1", "free")
        self.assertIsNone(resolve_user_business(self.db, u, client_id=None, url="https://a.com"))


class CreateClientReuseTests(_DB):
    def _create(self, user_id, name, url=None, client_id=None):
        payload = ClientCreate(id=client_id, name=name, url=url)
        return asyncio.run(create_client(payload, Response(), db=self.db, user_id=user_id))

    def _count(self, user_id):
        return self.db.query(Client).filter(Client.user_id == user_id).count()

    def test_rescan_reuses_business_no_duplicate(self):
        self.db.add(User(id="u1", email="u1@e.com", plan_tier="free"))
        self.db.commit()
        first = self._create("u1", "Pemspa", url="https://pemspa.com")
        # A "re-scan" comes back with no id and a www variant — must reuse, not duplicate.
        self._create("u1", "Pemspa", url="https://www.pemspa.com/")
        self.assertEqual(self._count("u1"), 1)
        # And edits update in place (same row).
        self.db.expire_all()
        only = self.db.query(Client).filter(Client.user_id == "u1").one()
        self.assertEqual(only.id, first.id)

    def test_first_business_is_created(self):
        self.db.add(User(id="u1", email="u1@e.com", plan_tier="free"))
        self.db.commit()
        self._create("u1", "Pemspa", url="https://pemspa.com")
        self.assertEqual(self._count("u1"), 1)

    def test_rescan_with_legacy_nonuuid_id_reuses_business(self):
        # Regression for the prod 422: a business kept with a legacy non-UUID id
        # (e.g. "pemspa_skincare_wellness") must be reusable by that id, not
        # rejected as "client_id must be a UUIDv4".
        self.db.add(User(id="u1", email="u1@e.com", plan_tier="custom"))
        self.db.add(Client(id="pemspa_skincare_wellness", user_id="u1",
                           name="PemSpa", url="https://pemspa.com/"))
        self.db.commit()
        res = self._create("u1", "PemSpa", url="https://pemspa.com/",
                           client_id="pemspa_skincare_wellness")
        self.assertEqual(res.id, "pemspa_skincare_wellness")  # reused, not 422, no new row
        self.assertEqual(self._count("u1"), 1)


if __name__ == "__main__":
    unittest.main()
