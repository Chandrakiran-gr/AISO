import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base, Client, ClientContext, Scan, User
from api.routes.pipeline import ScanCreate, start_scan
from api.scan_capabilities import (
    competitor_names_for_scan,
    group_capability_summary,
    validate_scan_group_capabilities,
)


class ScanCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _session_with_client(self, *, competitors=None, context_profile=None):
        session = self.Session()
        session.add(User(id="user-1", email="founder@example.com"))
        session.add(
            Client(
                id="client-1",
                user_id="user-1",
                name="AISO Demo",
                url="https://example.com",
                industry="Local service",
                location="Boston, MA",
                competitor_names=json.dumps(competitors) if competitors is not None else None,
            )
        )
        if context_profile is not None:
            session.add(
                ClientContext(
                    client_id="client-1",
                    status="confirmed",
                    profile_json=json.dumps(context_profile),
                )
            )
        session.commit()
        return session

    def test_capability_rules_make_competitors_optional_but_block_g3(self):
        ok, message = validate_scan_group_capabilities(["G3"], [])
        self.assertFalse(ok)
        self.assertIn("Add at least one competitor", message)

        ok, message = validate_scan_group_capabilities(["G7"], [])
        self.assertTrue(ok)
        self.assertIsNone(message)

        summary = group_capability_summary(["G3", "G7"], [])
        self.assertEqual(summary["unavailable_groups"], ["G3"])
        self.assertEqual(summary["reduced_groups"], ["G7"])

    def test_competitors_merge_from_client_and_confirmed_context(self):
        session = self._session_with_client(
            competitors=["Competitor A"],
            context_profile={"competitors": [{"name": "Competitor B"}, {"name": "Competitor A"}]},
        )
        try:
            client = session.query(Client).one()

            self.assertEqual(
                competitor_names_for_scan(client, {"competitors": [{"name": "Competitor B"}]}),
                ["Competitor A", "Competitor B"],
            )
        finally:
            session.close()

    def test_start_scan_rejects_g3_without_competitors(self):
        session = self._session_with_client()
        try:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    start_scan(
                        "client-1",
                        ScanCreate(client_id="client-1", providers=["gemini"], groups=["G3"]),
                        BackgroundTasks(),
                        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
                        db=session,
                        user_id="user-1",
                    )
                )

            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("Add at least one competitor", raised.exception.detail)
            self.assertEqual(session.query(Scan).count(), 0)
        finally:
            session.close()

    def test_start_scan_allows_g7_without_competitors_as_reduced_coverage(self):
        # Legacy-engine behavior: capability pass creates a legacy Scan row.
        session = self._session_with_client()
        try:
            with mock.patch.dict(os.environ, {"AISO_SCAN_ENGINE": "legacy"}):
                response = asyncio.run(
                    start_scan(
                        "client-1",
                        ScanCreate(client_id="client-1", providers=["gemini"], groups=["G7"]),
                        BackgroundTasks(),
                        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
                        db=session,
                        user_id="user-1",
                    )
                )

            self.assertEqual(response["status"], "pending")
            self.assertEqual(response["groups"], ["G7"])
            self.assertEqual(session.query(Scan).count(), 1)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
