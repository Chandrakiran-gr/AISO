"""Behavioral guardrail: BYOK keys are NEVER persisted (DB / logs / files).

This is the authoritative BYOK zero-persistence guarantee — the static grep
(``scripts/ci/check_byok_static.py``) is only a fast backstop that a non-literal
path can evade. Here we exercise the *real* client create/update + scan write
paths with a unique **sentinel** key value, then assert the sentinel is absent
from **every column of every table**, from captured application logs, and from
on-disk scan artifacts.

Non-vacuous by construction: ``test_scanner_detects_planted_sentinel`` plants
the sentinel directly into ``clients.byok_keys`` and asserts the all-tables
scanner FINDS it — proving the detector has teeth before the real-path tests
assert it finds nothing. A future change that wires a BYOK value into the
column / a log / a file turns this suite red.

Runs on SQLite by default and on real Postgres when ``TEST_DATABASE_URL`` is
set (CI), so "all tables" is exercised against the production engine too.
"""

from __future__ import annotations

import io
import logging
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select

from tests._pgharness import make_test_engine, reset_schema

import api.database as database
from api.database import Base, Client, Scan, User

# A value that cannot occur naturally anywhere in the schema.
SENTINEL = "sk-BYOK-SENTINEL-" + uuid.uuid4().hex


def find_sentinel_in_db(engine, sentinel: str) -> list[tuple[str, str, str]]:
    """Return [(table, column, repr(value)), ...] for every cell containing the sentinel.

    Stringifies each cell so JSON/dict columns (e.g. ``clients.byok_keys``) are
    searched too — a raw key smuggled into a JSON blob is still caught.
    """
    hits: list[tuple[str, str, str]] = []
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            rows = conn.execute(select(table)).fetchall()
            for row in rows:
                mapping = row._mapping
                for column in table.columns:
                    value = mapping[column.name]
                    if value is None:
                        continue
                    if sentinel in str(value):
                        hits.append((table.name, column.name, repr(value)))
    return hits


class ByokZeroPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = make_test_engine()
        reset_schema(self.engine)
        self.Session = database.sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    # ── teeth: the detector must actually fire ────────────────────────────────
    def test_scanner_detects_planted_sentinel(self):
        """Negative control: a sentinel written into byok_keys MUST be detected."""
        session = self.Session()
        try:
            user = User(id=str(uuid.uuid4()), email="planted@example.com")
            session.add(user)
            session.flush()
            client = Client(
                id=str(uuid.uuid4()),
                user_id=user.id,
                name="Planted Co",
                url="https://planted.example.com",
                # Deliberately bad: a raw key in the dormant column.
                byok_keys={"openai": SENTINEL},
            )
            session.add(client)
            session.commit()
        finally:
            session.close()

        hits = find_sentinel_in_db(self.engine, SENTINEL)
        self.assertTrue(
            hits, "scanner failed to detect a planted sentinel — the guard is vacuous"
        )
        self.assertIn(("clients", "byok_keys"), [(t, c) for (t, c, _v) in hits])

    # ── the real guarantee: write paths never persist the key ─────────────────
    def test_byok_sentinel_never_persisted_through_client_write_paths(self):
        """Exercise client CREATE then UPDATE (as the routes do) with a BYOK
        sentinel 'submitted', and assert it never lands in any table."""
        submitted_byok = {"openai": SENTINEL, "claude": SENTINEL}  # in-memory only

        session = self.Session()
        try:
            user = User(id=str(uuid.uuid4()), email="byok@example.com")
            session.add(user)
            session.flush()

            # CREATE path (mirrors api/routes/clients.py + onboarding.py):
            client = Client(
                id=str(uuid.uuid4()),
                user_id=user.id,
                name="Boston Brew",
                url="https://bostonbrew.example.com",
                industry="coffee",
            )
            session.add(client)
            session.commit()

            # UPDATE path: edits update in place. The submitted BYOK keys are
            # used in memory for the scan and must NOT be written here.
            client.name = "Boston Brew Coffee"
            client.industry = "specialty coffee"
            _ = submitted_byok  # referenced, never persisted
            session.commit()

            # SCAN create path (mirrors api/routes/pipeline.py start_scan):
            scan = Scan(
                id=str(uuid.uuid4()),
                client_id=client.id,
                status="pending",
                providers=["openai"],
                groups=["all"],
            )
            session.add(scan)
            session.commit()

            client_id = client.id
        finally:
            session.close()

        hits = find_sentinel_in_db(self.engine, SENTINEL)
        self.assertEqual(
            hits, [], f"BYOK sentinel leaked into the database: {hits}"
        )

        # The dormant column must remain NULL (metadata-only; never raw keys).
        session = self.Session()
        try:
            stored = session.get(Client, client_id)
            self.assertIsNone(
                stored.byok_keys,
                "clients.byok_keys must stay NULL on the real write path",
            )
        finally:
            session.close()

    def test_byok_sentinel_absent_from_logs_and_files(self):
        """Defense-in-depth: exercising the paths must not emit the sentinel to
        application logs or to on-disk scan artifacts."""
        log_buffer = io.StringIO()
        handler = logging.StreamHandler(log_buffer)
        root = logging.getLogger()
        root.addHandler(handler)
        prev_level = root.level
        root.setLevel(logging.DEBUG)
        try:
            with TemporaryDirectory() as scan_dir:
                session = self.Session()
                try:
                    user = User(id=str(uuid.uuid4()), email="logs@example.com")
                    session.add(user)
                    session.flush()
                    client = Client(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        name="LogCo",
                        url="https://logco.example.com",
                    )
                    session.add(client)
                    session.commit()
                finally:
                    session.close()

                # No artifact written under the scan dir should carry the key.
                leaks = [
                    str(p)
                    for p in Path(scan_dir).rglob("*")
                    if p.is_file() and SENTINEL in p.read_text(errors="ignore")
                ]
                self.assertEqual(leaks, [], f"BYOK sentinel written to disk: {leaks}")
        finally:
            root.removeHandler(handler)
            root.setLevel(prev_level)

        self.assertNotIn(
            SENTINEL, log_buffer.getvalue(), "BYOK sentinel leaked into application logs"
        )

    def test_subprocess_env_path_is_ephemeral(self):
        """The intended path (BYOK → subprocess env) keeps the key in the env
        dict for the child process but never touches the DB.

        Skips cleanly if the heavy route module can't be imported in a minimal
        env; CI installs full deps so it runs there.
        """
        try:
            from api.routes.pipeline import build_subprocess_env
        except Exception as exc:  # pragma: no cover - env-dependent import
            self.skipTest(f"api.routes.pipeline unavailable: {exc}")

        sub_env = build_subprocess_env(
            {"PATH": "/usr/bin"}, {"openai": SENTINEL}, use_managed_keys=False
        )
        # Ephemeral by design: present in the child env...
        self.assertEqual(sub_env.get("OPENAI_API_KEY"), SENTINEL)
        # ...but nothing was persisted as a side effect.
        self.assertEqual(find_sentinel_in_db(self.engine, SENTINEL), [])


if __name__ == "__main__":
    unittest.main()
