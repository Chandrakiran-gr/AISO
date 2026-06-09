"""P3 consolidation: keep one canonical business per (user, url), delete the rest."""

import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import Base, Client, ClientContext, Scan, User
from scripts.consolidate_duplicate_clients import consolidate, plan_consolidation


class ConsolidateDuplicateClientsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(self.engine, "connect")
        def _fk_on(dbapi_con, _rec):  # SQLite needs this for ON DELETE CASCADE
            dbapi_con.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(User(id="u1", email="u1@e.com", plan_tier="custom"))
        self.db.flush()  # parent rows must exist before children (FK enforced immediately)
        # One business, three duplicate rows (scheme/www variants group together).
        self._client("keep", "Pemspa", "https://pemspa.com", scans=2, confirmed=True)
        self._client("dup1", "Pemspa", "https://www.pemspa.com/", scans=1)
        self._client("dup2", "Pemspa", "https://pemspa.com", scans=0)
        # A separate, single business — must be left untouched.
        self._client("solo", "Other", "https://other.com", scans=1)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _client(self, cid, name, url, *, scans=0, confirmed=False):
        self.db.add(Client(id=cid, user_id="u1", name=name, url=url))
        self.db.flush()  # client must exist before its context/scans (FK)
        if confirmed:
            self.db.add(ClientContext(client_id=cid, status="confirmed"))
        for i in range(scans):
            self.db.add(Scan(id=f"{cid}-s{i}", client_id=cid, status="complete"))

    def _client_ids(self):
        return {c.id for c in self.db.query(Client).all()}

    def _scan_ids(self):
        return {s.id for s in self.db.query(Scan).all()}

    def test_dry_run_picks_confirmed_canonical_and_changes_nothing(self):
        plan = plan_consolidation(self.db)
        self.assertEqual(len(plan), 1)  # only the duplicate group; solo excluded
        group = plan[0]
        self.assertEqual(group["canonical"]["client"].id, "keep")  # confirmed context wins
        self.assertEqual({d["client"].id for d in group["duplicates"]}, {"dup1", "dup2"})
        self.assertEqual(self._client_ids(), {"keep", "dup1", "dup2", "solo"})  # untouched

    def test_apply_keeps_canonical_deletes_duplicates_and_their_scans(self):
        consolidate(self.db, apply=True)
        self.db.expire_all()
        self.assertEqual(self._client_ids(), {"keep", "solo"})
        # Canonical + solo scans kept; the duplicates' scans cascade-deleted.
        self.assertEqual(self._scan_ids(), {"keep-s0", "keep-s1", "solo-s0"})

    def test_apply_is_idempotent(self):
        consolidate(self.db, apply=True)
        self.db.expire_all()
        self.assertEqual(plan_consolidation(self.db), [])

    def test_pin_overrides_canonical_choice(self):
        plan = plan_consolidation(self.db, pinned={"dup1"})
        self.assertEqual(plan[0]["canonical"]["client"].id, "dup1")


if __name__ == "__main__":
    unittest.main()
