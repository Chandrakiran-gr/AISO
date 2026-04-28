import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.client_context_service import build_context_profile
from api.database import Base, Client, ClientContext, User
from api.routes.client_context import (
    ClientContextUpdate,
    _run_context_discovery,
    discover_client_context,
    get_client_context,
    update_client_context,
)


class ClientContextProfileTests(unittest.TestCase):
    def test_pempsa_fixture_classifies_groups_offerings_and_product_brands(self):
        client = Client(
            id="pempsa",
            user_id="user-1",
            name="Pempsa",
            url="https://pempsa.example",
            industry="boutique skincare spa",
            location="Newton Centre, MA",
            competitors=json.dumps(["Bella Boutique Spa"]),
        )
        evidence = {
            "pages": [
                {
                    "url": "https://pempsa.example/services",
                    "title": "Pempsa Services",
                    "headings": ["Signature Facials"],
                    "text_blocks": [
                        "Chemical Peel $175 50 minutes",
                        "Deluxe Dermaplane Facial $145 45 minutes",
                        "We use Face Reality products for acne-safe skincare.",
                        "Serving Newton Centre and surrounding areas including Brookline, Chestnut Hill, Needham, Wellesley.",
                    ],
                    "json_ld": [],
                    "forms": [],
                }
            ],
            "warnings": [],
        }

        profile, warnings, status = build_context_profile(client, evidence)

        self.assertIn(status, {"draft", "needs_review"})
        self.assertIn("Signature Facials", {item["name"] for item in profile["offering_groups"]})
        self.assertIn("Chemical Peel", {item["name"] for item in profile["offerings"]})
        self.assertIn("Deluxe Dermaplane Facial", {item["name"] for item in profile["offerings"]})
        self.assertIn("Face Reality", {item["name"] for item in profile["product_brands"]})
        self.assertEqual(profile["competitors"][0]["type"], "competitor_business")
        self.assertNotIn("No services found.", warnings)

    def test_pempsa_style_real_pages_keep_groups_out_of_bookable_services(self):
        client = Client(
            id="pempsa-realistic",
            user_id="user-1",
            name="PemSpa",
            url="https://www.pemspa.com/",
            industry="boutique skincare spa / facial spa",
            location="Newton Centre, MA",
            competitors=json.dumps(["Bella Boutique Spa", "Christine's Day Spa"]),
        )
        evidence = {
            "pages": [
                {
                    "url": "https://pemspa.com/",
                    "title": "PemSpa Skincare & Wellness",
                    "headings": ["Signature Facials", "Advanced Facials"],
                    "text_blocks": [
                        "Sign In My Account Bookings",
                        "Proudly serving Newton, Chestnut Hill, Brookline, Needham, and nearby Greater Boston communities since 2021.",
                        "634 Commonwealth Avenue, Suite 209, Newton, Massachusetts 02459",
                    ],
                    "json_ld": [],
                    "forms": [],
                },
                {
                    "url": "https://pemspa.com/signature-facials",
                    "title": "Signature Facials",
                    "headings": [
                        "Signature Skin Health Facials",
                        "BALANCED BLISS Classic Facial",
                        "Deluxe Dermaplane Facial",
                        "Chemical Peel",
                    ],
                    "text_blocks": [
                        "Book Now",
                        "Dermaplaning gently exfoliates and removes peach fuzz.",
                    ],
                    "json_ld": [],
                    "forms": [],
                },
                {
                    "url": "https://pemspa.com/advanced-facials",
                    "title": "Advanced Facials",
                    "headings": [
                        "Advanced Transformation Facials",
                        "Lift and Tighten Anti-Aging Facial",
                        "DermaPeel Renewal Facial (Dermaplane + Peel)",
                        "Acne Clearing Oxygen Facial",
                    ],
                    "text_blocks": [],
                    "json_ld": [],
                    "forms": [],
                },
            ],
            "warnings": [],
            "page_count": 3,
        }

        profile, warnings, status = build_context_profile(client, evidence)

        groups = {item["name"] for item in profile["offering_groups"]}
        offerings = {item["name"] for item in profile["offerings"]}
        categories = {item["name"] for item in profile["categories"]}

        self.assertEqual(status, "draft")
        self.assertIn("Signature Facials", groups)
        self.assertIn("Advanced Facials", groups)
        self.assertNotIn("Signature Facials", offerings)
        self.assertNotIn("Advanced Facials", offerings)
        self.assertIn("Chemical Peel", offerings)
        self.assertIn("Deluxe Dermaplane Facial", offerings)
        self.assertNotIn("home service", categories)
        self.assertNotIn("No services found.", warnings)


class ClientContextApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_discover_context_is_user_scoped_and_persists_safe_draft(self):
        session = self.Session()
        try:
            session.add(User(id="user-1", email="founder@example.com"))
            session.add(User(id="user-2", email="other@example.com"))
            session.add(
                Client(
                    id="client-1",
                    user_id="user-1",
                    name="Pempsa",
                    url="https://pempsa.example",
                    industry="skincare spa",
                )
            )
            session.commit()

            evidence = {
                "pages": [
                    {
                        "url": "https://pempsa.example/services",
                        "title": "Services",
                        "headings": ["Signature Facials"],
                        "text_blocks": ["Chemical Peel $175 50 minutes"],
                        "json_ld": [],
                        "forms": [],
                    }
                ],
                "warnings": [],
                "page_count": 1,
            }
            with (
                patch("api.routes.client_context.discover_website", return_value=evidence),
                patch("api.routes.client_context.SessionLocal", self.Session),
            ):
                response = asyncio.run(
                    discover_client_context(
                        "client-1",
                        BackgroundTasks(),
                        db=session,
                        user_id="user-1",
                    )
                )
                _run_context_discovery("client-1")

            self.assertEqual(response.client_id, "client-1")
            self.assertEqual(response.status, "discovering")
            session.expire_all()
            stored_context = session.query(ClientContext).one()
            self.assertIn(stored_context.status, {"draft", "needs_review"})
            self.assertEqual(session.query(ClientContext).count(), 1)

            with self.assertRaises(Exception):
                asyncio.run(get_client_context("client-1", db=session, user_id="user-2"))
        finally:
            session.close()

    def test_update_context_confirms_profile(self):
        session = self.Session()
        try:
            session.add(User(id="user-1", email="founder@example.com"))
            session.add(
                Client(
                    id="client-1",
                    user_id="user-1",
                    name="AISO Demo",
                    url="https://example.com",
                )
            )
            session.commit()

            response = asyncio.run(
                update_client_context(
                    "client-1",
                    ClientContextUpdate(
                        status="confirmed",
                        profile_json={
                            "business": {"name": "AISO Demo"},
                            "categories": [],
                            "offering_groups": [],
                            "offerings": [{"name": "Visibility Scan", "type": "offering"}],
                            "product_brands": [],
                            "competitors": [],
                            "locations": {
                                "physical_locations": [],
                                "service_areas": [],
                                "visibility_markets": [],
                                "excluded_locations": [],
                            },
                            "goals": [],
                            "personas": [],
                            "differentiators": [],
                            "guardrails": [],
                        },
                        warnings_json=[],
                    ),
                    db=session,
                    user_id="user-1",
                )
            )

            self.assertEqual(response.status, "confirmed")
            stored = session.query(ClientContext).one()
            self.assertIsNotNone(stored.updated_at)
            self.assertEqual(json.loads(stored.profile_json)["business"]["name"], "AISO Demo")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
