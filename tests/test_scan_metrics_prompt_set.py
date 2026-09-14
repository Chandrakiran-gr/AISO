"""The onboarding-approved prompt set must score, and must not hide old scans.

The redesigned onboarding sends the approved prompt list as ``custom_questions``
with no groups, so the legacy engine files every row under ``MANUAL``. Analytics
used to strip that group - a rule written for a handful of ad-hoc questions back
when G1-G7 was the real question set. The result in production: a scan that
completed all 192 provider calls reported no metrics at all, and because the
selection loop stopped at the newest scan holding *any* rows, the previous good
scan stopped rendering too.
"""

import asyncio
import unittest

from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from api.database import Client, Scan, ScanResult, User
from api.routes.pipeline import get_client_metrics, get_scan_metrics_timeline
from tests._pgharness import make_test_engine, reset_schema


class PromptSetScanMetricsTests(unittest.TestCase):
    def setUp(self):
        self.engine = make_test_engine()
        reset_schema(self.engine)
        # autoflush=False mirrors the prod session: the unit of work will not
        # quietly reorder our INSERTs to satisfy foreign keys.
        self.Session = sessionmaker(bind=self.engine, autoflush=False)

    def tearDown(self):
        self.engine.dispose()

    def _seed_client(self, session):
        session.add(User(id="user-1", email="founder@example.com"))
        session.add(
            Client(
                id="client-1",
                user_id="user-1",
                name="PemSpa",
                url="https://pemspa.example",
                competitor_names=["Glowbar"],
            )
        )
        # Parent rows must land before any child row references them.
        session.flush()

    def _add_scan(self, session, scan_id, created_at, rows):
        session.add(
            Scan(
                id=scan_id,
                client_id="client-1",
                status="complete",
                providers=["openai", "perplexity"],
                groups=[group for group, _, _ in rows],
                created_at=created_at,
            )
        )
        session.flush()
        for index, (group, total, mentions) in enumerate(rows):
            session.add(
                ScanResult(
                    id=f"{scan_id}-r{index}",
                    scan_id=scan_id,
                    client_id="client-1",
                    provider="openai" if index % 2 == 0 else "perplexity",
                    group=group,
                    total_questions=total,
                    mention_count=mentions,
                    visibility_score=100.0 * mentions / total,
                )
            )
        session.flush()

    def _metrics(self, session, scan_id=None):
        return asyncio.run(
            get_client_metrics(
                "client-1", scan_id=scan_id, db=session, user_id="user-1"
            )
        )

    def test_prompt_set_scan_produces_metrics(self):
        """A scan whose questions are all MANUAL still scores."""
        session = self.Session()
        try:
            self._seed_client(session)
            self._add_scan(
                session,
                "scan-prompts",
                _dt(2026, 9, 14),
                [("MANUAL", 48, 9), ("MANUAL", 48, 13)],
            )
            session.commit()

            metrics = self._metrics(session)
            self.assertEqual(metrics.total_questions, 96)
            self.assertEqual(
                sum(item.mention_count for item in metrics.provider_metrics), 22
            )
        finally:
            session.close()

    def test_prompt_set_scan_does_not_hide_earlier_scans(self):
        """The reported bug: a new scan must never blank out scan history."""
        session = self.Session()
        try:
            self._seed_client(session)
            self._add_scan(
                session,
                "scan-june",
                _dt(2026, 6, 17),
                [("G1", 8, 8), ("G2", 8, 8)],
            )
            self._add_scan(
                session,
                "scan-september",
                _dt(2026, 9, 14),
                [("MANUAL", 48, 9), ("MANUAL", 48, 13)],
            )
            session.commit()

            # The older scan is still reachable on its own...
            june = self._metrics(session, scan_id="scan-june")
            self.assertEqual(june.total_questions, 16)

            # ...and the newer one answers the unfiltered dashboard call rather
            # than 404ing and taking the June scan down with it.
            latest = self._metrics(session)
            self.assertEqual(latest.total_questions, 96)
        finally:
            session.close()

    def test_scan_without_usable_rows_falls_through_to_older_scan(self):
        """Selection and filtering share one predicate, so nothing shadows."""
        session = self.Session()
        try:
            self._seed_client(session)
            self._add_scan(session, "scan-good", _dt(2026, 6, 17), [("G1", 8, 6)])
            # A newer scan that produced no result rows at all.
            self._add_scan(session, "scan-empty", _dt(2026, 9, 14), [])
            session.commit()

            metrics = self._metrics(session)
            self.assertEqual(metrics.total_questions, 8)
            self.assertEqual(metrics.scan_id, "scan-good")
        finally:
            session.close()

    def test_client_with_no_results_still_404s(self):
        session = self.Session()
        try:
            self._seed_client(session)
            self._add_scan(session, "scan-empty", _dt(2026, 9, 14), [])
            session.commit()

            with self.assertRaises(HTTPException) as caught:
                self._metrics(session)
            self.assertEqual(caught.exception.status_code, 404)
        finally:
            session.close()

    def test_timeline_marks_the_methodology_change(self):
        """Scores either side of the prompt-set switch are not comparable."""
        session = self.Session()
        try:
            self._seed_client(session)
            self._add_scan(
                session,
                "scan-june",
                _dt(2026, 6, 17),
                [("G1", 8, 8), ("G2", 8, 8)],
            )
            self._add_scan(
                session,
                "scan-september",
                _dt(2026, 9, 14),
                [("MANUAL", 48, 9), ("MANUAL", 48, 13)],
            )
            session.commit()

            points = asyncio.run(
                get_scan_metrics_timeline(
                    client_id="client-1", db=session, user_id="user-1"
                )
            )
            by_scan = {point.scan_id: point.methodology for point in points}
            self.assertEqual(by_scan["scan-june"], "group_bank")
            self.assertEqual(by_scan["scan-september"], "prompt_set")
        finally:
            session.close()


def _dt(year, month, day):
    from datetime import datetime, timezone

    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


if __name__ == "__main__":
    unittest.main()
