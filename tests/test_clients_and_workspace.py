import asyncio
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base, Client, User
from api.routes.clients import ClientCreate, create_client, list_clients
from api.scan_workspace import prepare_scan_workspace


class ClientProfileTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def test_create_client_persists_full_onboarding_profile_and_updates_same_user(self):
        session = self.Session()
        try:
            session.add(User(id="user-1", email="founder@example.com"))
            session.commit()

            created = asyncio.run(
                create_client(
                    ClientCreate(
                        id="acme_widgets",
                        display_name="Acme Widgets",
                        url="https://acme.example",
                        industry="Industrial widgets",
                        location="Boston, MA",
                        competitors=["WidgetCo", "Parts Plus"],
                    ),
                    response=Response(),
                    db=session,
                    user_id="user-1",
                )
            )

            self.assertEqual(created.id, "acme_widgets")
            self.assertEqual(created.url, "https://acme.example")
            self.assertEqual(created.industry, "Industrial widgets")
            self.assertEqual(created.location, "Boston, MA")
            self.assertEqual(created.competitors, ["WidgetCo", "Parts Plus"])

            updated = asyncio.run(
                create_client(
                    ClientCreate(
                        id="acme_widgets",
                        display_name="Acme Widgets Updated",
                        url="https://new.example",
                        industry="B2B software",
                        location="New York, NY",
                        competitors=["New Rival"],
                    ),
                    response=Response(),
                    db=session,
                    user_id="user-1",
                )
            )

            self.assertEqual(updated.name, "Acme Widgets Updated")
            self.assertEqual(updated.url, "https://new.example")
            self.assertEqual(updated.competitors, ["New Rival"])

            listed = asyncio.run(list_clients(db=session, user_id="user-1"))
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].name, "Acme Widgets Updated")
        finally:
            session.close()


class ScanWorkspaceTests(unittest.TestCase):
    def test_prepare_scan_workspace_creates_collect_inputs(self):
        client = Client(
            id="Acme Widgets",
            user_id="user-1",
            name="Acme Widgets",
            url="https://acme.example",
            industry="Industrial widgets",
            location="Boston, MA",
            competitors=json.dumps(["WidgetCo", "Parts Plus"]),
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("api.scan_workspace.CLIENTS_ROOT", Path(tmp)):
                folder = prepare_scan_workspace(client)

            self.assertEqual(folder.name, "acme_widgets")
            self.assertTrue((folder / "client_profile.json").exists())
            self.assertTrue((folder / "value_bank.csv").exists())
            self.assertTrue((folder / "query_template_bank.csv").exists())

            profile = json.loads((folder / "client_profile.json").read_text())
            self.assertEqual(profile["display_name"], "Acme Widgets")
            self.assertEqual(profile["competitors"], ["WidgetCo", "Parts Plus"])

            with (folder / "query_template_bank.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertGreaterEqual(len(rows), 7)
            self.assertEqual({row["group"] for row in rows}, {"G1", "G2", "G3", "G4", "G5", "G6", "G7"})


if __name__ == "__main__":
    unittest.main()
