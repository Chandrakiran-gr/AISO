import asyncio
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException, Response
from sqlalchemy.orm import sessionmaker

from tests._pgharness import make_test_engine, reset_schema
from api.database import Base, Client, User
from api.routes.clients import ClientCreate, create_client, list_clients
from api.scan_workspace import prepare_scan_workspace


class ClientProfileTests(unittest.TestCase):
    def setUp(self):
        self.engine = make_test_engine()  # Postgres when TEST_DATABASE_URL set, else SQLite
        reset_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_create_client_persists_full_onboarding_profile_and_updates_same_user(self):
        session = self.Session()
        try:
            session.add(User(id="user-1", email="founder@example.com"))
            session.commit()

            created = asyncio.run(
                create_client(
                    ClientCreate(
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

            self.assertEqual(UUID(created.id, version=4).version, 4)
            self.assertEqual(created.url, "https://acme.example/")  # canonicalized on write
            self.assertEqual(created.industry, "Industrial widgets")
            self.assertEqual(created.location, "Boston, MA")
            self.assertEqual(created.competitors, ["WidgetCo", "Parts Plus"])

            updated = asyncio.run(
                create_client(
                    ClientCreate(
                        id=created.id,
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
            self.assertEqual(updated.url, "https://new.example/")  # canonicalized on write
            self.assertEqual(updated.competitors, ["New Rival"])

            listed = asyncio.run(list_clients(db=session, user_id="user-1"))
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].name, "Acme Widgets Updated")
        finally:
            session.close()

    def test_create_client_ignores_caller_supplied_id_and_mints_uuid(self):
        # A caller-supplied id is never honored for a NEW business (no id injection);
        # the server mints a UUIDv4. Non-UUID ids are no longer 422'd — legacy
        # clients have non-UUID ids and must stay reusable (see the reuse test in
        # tests/test_client_identity.py).
        session = self.Session()
        try:
            session.add(User(id="user-1", email="founder@example.com"))
            session.commit()

            created = asyncio.run(
                create_client(
                    ClientCreate(
                        id="second_business",
                        display_name="Second Business",
                        url="https://second.example",
                    ),
                    response=Response(),
                    db=session,
                    user_id="user-1",
                )
            )
            self.assertEqual(UUID(created.id, version=4).version, 4)  # server-minted UUID
            self.assertNotEqual(created.id, "second_business")        # caller id not honored
            self.assertEqual(session.query(Client).filter(Client.user_id == "user-1").count(), 1)
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
            competitor_names=["WidgetCo", "Parts Plus"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("api.scan_workspace.CLIENTS_ROOT", Path(tmp)):
                folder = prepare_scan_workspace(client)

            self.assertEqual(folder.name, "acme_widgets__c994aab0")
            self.assertTrue((folder / "client_profile.json").exists())
            self.assertTrue((folder / "value_bank.csv").exists())
            self.assertTrue((folder / "query_template_bank.csv").exists())

            profile = json.loads((folder / "client_profile.json").read_text())
            self.assertEqual(profile["slug"], "acme_widgets")
            self.assertEqual(profile["display_name"], "Acme Widgets")
            self.assertEqual(profile["competitors"], ["WidgetCo", "Parts Plus"])

            with (folder / "query_template_bank.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertGreaterEqual(len(rows), 7)
            self.assertEqual({row["group"] for row in rows}, {"G1", "G2", "G3", "G4", "G5", "G6", "G7"})

    def test_prepare_scan_workspace_uses_current_business_name_for_public_slug(self):
        client = Client(
            id="pemspa",
            user_id="user-1",
            name="AISO Global",
            url="https://aisoglobal.com",
            industry="AI visibility software",
            location="United States",
            competitor_names=["Profound", "Scrunch"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("api.scan_workspace.CLIENTS_ROOT", Path(tmp)):
                folder = prepare_scan_workspace(client)

            profile = json.loads((folder / "client_profile.json").read_text())
            config = json.loads((folder / "config.json").read_text())

        self.assertTrue(folder.name.startswith("aiso_global__"))
        self.assertNotIn("pemspa", folder.name)
        self.assertEqual(profile["slug"], "aiso_global")
        self.assertEqual(config["slug"], "aiso_global")

    def test_prepare_scan_workspace_uses_confirmed_context_profile(self):
        client = Client(
            id="pempsa",
            user_id="user-1",
            name="Pempsa",
            url="https://pempsa.example",
            industry="Spa",
            location="Greater Boston",
            competitor_names=None,
        )
        context_profile = {
            "business": {"name": "Pempsa"},
            "categories": [{"name": "boutique skincare spa", "type": "category"}],
            "offering_groups": [{"name": "Signature Facials", "type": "offering_group", "bookable": False}],
            "offerings": [{"name": "Chemical Peel", "type": "offering", "bookable": True}],
            "product_brands": [{"name": "Face Reality", "type": "product_brand"}],
            "competitors": [{"name": "Bella Boutique Spa", "type": "competitor_business"}],
            "locations": {
                "physical_locations": [{"name": "Newton Centre, MA", "type": "physical_location"}],
                "service_areas": [],
                "visibility_markets": [{"name": "Greater Boston", "type": "visibility_market"}],
                "excluded_locations": [],
            },
            "goals": [{"name": "improve acne-prone skin", "type": "goal"}],
            "personas": [{"name": "first-time facial clients", "type": "persona"}],
            "differentiators": [],
            "guardrails": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch("api.scan_workspace.CLIENTS_ROOT", Path(tmp)):
                folder = prepare_scan_workspace(client, context_profile=context_profile, selected_groups=["G2", "G4"])

            profile = json.loads((folder / "client_profile.json").read_text())
            self.assertEqual(profile["confirmed_context"]["offerings"][0]["name"], "Chemical Peel")
            self.assertEqual(profile["competitors"], ["Bella Boutique Spa"])
            self.assertTrue((folder / "question_ranking_report.json").exists())

            with (folder / "query_template_bank.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            questions = {row["question"] for row in rows}
            self.assertIn("Pempsa chemical peel?", questions)
            self.assertNotIn("Chemical Peel vs Bella Boutique Spa: which is better?", questions)
            self.assertEqual({row["group"] for row in rows}, {"G2", "G4"})
            self.assertTrue(all(row["final_rank_score"] for row in rows))

    def test_prepare_scan_workspace_g7_without_competitors_has_reduced_non_placeholder_coverage(self):
        client = Client(
            id="acme_widgets",
            user_id="user-1",
            name="Acme Widgets",
            url="https://acme.example",
            industry="Home repair service",
            location="Boston, MA",
            competitor_names=None,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("api.scan_workspace.CLIENTS_ROOT", Path(tmp)):
                folder = prepare_scan_workspace(client, selected_groups=["G7"])

            with (folder / "query_template_bank.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        questions = "\n".join(row["question"] for row in rows).casefold()
        self.assertTrue(rows)
        self.assertEqual({row["group"] for row in rows}, {"G7"})
        self.assertNotIn("another local business", questions)
        self.assertNotIn("leading competitor", questions)
        self.assertFalse(any(row["intent_subtype"] == "head_to_head" for row in rows))
        self.assertTrue(any(row["intent_subtype"] in {"method_comparison", "adjacency"} for row in rows))

    def test_prepare_scan_workspace_appends_scan_specific_manual_questions_only_once(self):
        client = Client(
            id="acme_widgets",
            user_id="user-1",
            name="Acme Widgets",
            url="https://acme.example",
            industry="Home repair service",
            location="Boston, MA",
            competitor_names=["Rival Home Co"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("api.scan_workspace.CLIENTS_ROOT", Path(tmp)):
                folder = prepare_scan_workspace(
                    client,
                    selected_groups=["G1"],
                    custom_questions=[
                        "Does Acme Widgets show up for emergency repair questions?",
                        "What sources recommend Acme Widgets for Boston homeowners?",
                    ],
                )
                with (folder / "query_template_bank.csv").open(newline="", encoding="utf-8") as handle:
                    rows_with_manual = list(csv.DictReader(handle))

                folder_without_manual = prepare_scan_workspace(
                    client,
                    selected_groups=["G1"],
                    custom_questions=[],
                )
                with (folder_without_manual / "query_template_bank.csv").open(newline="", encoding="utf-8") as handle:
                    rows_without_manual = list(csv.DictReader(handle))

        manual_rows = [row for row in rows_with_manual if row["group"] == "MANUAL"]
        self.assertEqual(len(manual_rows), 2)
        self.assertEqual(manual_rows[0]["group_label"], "Custom Questions")
        self.assertEqual(manual_rows[0]["group_rank"], "1")
        self.assertEqual(manual_rows[0]["intent_subtype"], "client_authored")
        self.assertEqual(manual_rows[1]["group_rank"], "2")
        self.assertFalse([row for row in rows_without_manual if row["group"] == "MANUAL"])

    def test_prepare_scan_workspace_can_write_optional_extended_bank(self):
        client = Client(
            id="pempsa",
            user_id="user-1",
            name="Pempsa",
            url="https://pempsa.example",
            industry="Spa",
            location="Greater Boston",
            competitor_names=["Bella Boutique Spa"],
        )
        context_profile = {
            "business": {"name": "Pempsa"},
            "categories": [{"name": "boutique skincare spa", "type": "category"}],
            "offering_groups": [{"name": "Signature Facials", "type": "offering_group", "bookable": False}],
            "offerings": [
                {"name": "Chemical Peel", "type": "offering", "bookable": True},
                {"name": "Deluxe Dermaplane Facial", "type": "offering", "bookable": True},
            ],
            "product_brands": [{"name": "Face Reality", "type": "product_brand"}],
            "competitors": [{"name": "Bella Boutique Spa", "type": "competitor_business"}],
            "locations": {
                "physical_locations": [{"name": "Newton Centre, MA", "type": "physical_location"}],
                "service_areas": [{"name": "Brookline", "type": "service_area"}],
                "visibility_markets": [{"name": "Greater Boston", "type": "visibility_market"}],
                "excluded_locations": [],
            },
            "goals": [{"name": "improve acne-prone skin", "type": "goal"}],
            "personas": [{"name": "first-time facial clients", "type": "persona"}],
            "differentiators": [],
            "guardrails": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch("api.scan_workspace.CLIENTS_ROOT", Path(tmp)):
                with patch.dict(
                    "os.environ",
                    {
                        "AISO_QUESTION_WRITE_EXTENDED_BANK": "1",
                        "AISO_QUESTION_EXTENDED_GROUP_TARGETS": "G1:10,G2:10",
                    },
                    clear=False,
                ):
                    folder = prepare_scan_workspace(client, context_profile=context_profile, selected_groups=["G1", "G2"])

            self.assertTrue((folder / "query_template_bank_extended.csv").exists())
            self.assertTrue((folder / "question_ranking_report_extended.json").exists())

            with (folder / "query_template_bank.csv").open(newline="", encoding="utf-8") as handle:
                base_rows = list(csv.DictReader(handle))
            with (folder / "query_template_bank_extended.csv").open(newline="", encoding="utf-8") as handle:
                extended_rows = list(csv.DictReader(handle))

            self.assertGreaterEqual(len(extended_rows), len(base_rows))
            self.assertTrue(all(row["market_rationale"] for row in extended_rows))


if __name__ == "__main__":
    unittest.main()
