import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks
from pydantic import ValidationError
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
            competitor_names=["Bella Boutique Spa"],
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
        self.assertEqual(profile["scan_objective"]["optimization_objectives"], [])
        self.assertTrue(profile["buyer_contexts"])
        self.assertNotIn("No services found.", warnings)

    def test_pempsa_style_real_pages_keep_groups_out_of_bookable_services(self):
        client = Client(
            id="pempsa-realistic",
            user_id="user-1",
            name="PemSpa",
            url="https://www.pemspa.com/",
            industry="boutique skincare spa / facial spa",
            location="Newton Centre, MA",
            competitor_names=["Bella Boutique Spa", "Christine's Day Spa"],
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
                        "634 Commonwealth Avenue suite 209, Newton Centre, Newton, Newton Centre, Massachusetts 02459",
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
                        "The Hydro Boost Add-On is the perfect solution, featuring PAIN-FREE extractions.",
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
        product_brands = {item["name"] for item in profile["product_brands"]}
        physical_locations = [item["name"] for item in profile["locations"]["physical_locations"]]

        self.assertEqual(status, "draft")
        self.assertIn("Signature Facials", groups)
        self.assertIn("Advanced Facials", groups)
        self.assertNotIn("Signature Facials", offerings)
        self.assertNotIn("Advanced Facials", offerings)
        self.assertIn("Chemical Peel", offerings)
        self.assertIn("Deluxe Dermaplane Facial", offerings)
        self.assertNotIn("PAIN", product_brands)
        self.assertEqual(len(physical_locations), 1)
        self.assertNotIn("Newton Centre, Newton, Newton Centre", physical_locations[0])
        self.assertNotIn("home service", categories)
        self.assertNotIn("No services found.", warnings)

    def test_persona_evidence_is_cleaned_into_searchable_segments(self):
        client = Client(
            id="pempsa-persona",
            user_id="user-1",
            name="PemSpa",
            url="https://pempsa.example",
            industry="boutique skincare spa",
        )
        persona_text = (
            "✨ Ideal for sensitive skin or anyone wanting hydrated, radiant results without harsh abrasion. "
            "Removes unwanted hair from the chin area for a smooth, clean look. "
            "We use gentle wax suitable for sensitive skin and first-time waxing clients. "
            "Ideal for mature to improve firmness. "
            "Good for sensitive skin to minimize irritation. >Book Now"
        )
        evidence = {
            "pages": [
                {
                    "url": "https://pempsa.example/signature-facials",
                    "title": "Signature Facials",
                    "headings": ["Chemical Peel"],
                    "text_blocks": [persona_text],
                    "json_ld": [],
                    "forms": [],
                }
            ],
            "warnings": [],
        }

        profile, _, _ = build_context_profile(client, evidence)

        persona_names = [item["name"] for item in profile["personas"]]
        combined = " ".join(persona_names).casefold()

        self.assertIn("sensitive skin", combined)
        self.assertIn("mature skin", combined)
        self.assertIn("first-time waxing clients", combined)
        self.assertNotIn("sensitive skin to minimize irritation", persona_names)
        self.assertFalse(any("Book Now" in name for name in persona_names))
        self.assertFalse(any("Ideal for" in name for name in persona_names))
        self.assertFalse(any("Removes unwanted hair" in name for name in persona_names))
        self.assertFalse(any("✨" in name for name in persona_names))
        self.assertFalse(
            any(
                name in {
                    "your skin",
                    "those",
                    "anyone with light",
                    "straight, light",
                    "straight",
                    "light",
                    "regular skin maintenance",
                    "regular maintenance with minimal irritation",
                }
                for name in persona_names
            )
        )

    def test_scraped_marketing_copy_is_not_promoted_to_profile_entities(self):
        client = Client(
            id="pempsa-noise",
            user_id="user-1",
            name="PemSpa",
            url="https://pempsa.example",
            industry="boutique skincare spa",
        )
        evidence = {
            "pages": [
                {
                    "url": "https://pempsa.example/services",
                    "title": "Services",
                    "headings": [
                        "✨ Ideal for sensitive skin or anyone wanting hydrated, radiant results without harsh abrasion.",
                        "Defined, lifted, and polished. Brow and lash treatments that frame the face.",
                        "Brow, Lash, and Wax Treatments | PemSpa Newton",
                        "ADDITIONAL Facial ADD-ONS:",
                        "Chemical Peel",
                    ],
                    "text_blocks": [
                        "We use gentle wax suitable for sensitive skin and first-time waxing clients.",
                        "The Hydro Boost Add-On is the perfect solution, featuring PAIN-FREE extractions.",
                        "Chemical Peel $175 50 minutes",
                    ],
                    "json_ld": [],
                    "forms": [],
                }
            ],
            "warnings": [],
        }

        profile, _, _ = build_context_profile(client, evidence)
        entity_names = []
        for key in ("categories", "offering_groups", "offerings", "product_brands", "personas"):
            entity_names.extend(item["name"] for item in profile[key])
        combined = "\n".join(entity_names)

        self.assertIn("Chemical Peel", {item["name"] for item in profile["offerings"]})
        self.assertNotIn("ADDITIONAL Facial ADD-ONS:", combined)
        self.assertIn("Brow, Lash, and Wax Treatments", combined)
        self.assertNotIn("Brow, Lash, and Wax Treatments | PemSpa Newton", combined)
        self.assertNotIn("Defined, lifted, and polished", combined)
        self.assertNotIn("Ideal for sensitive skin", combined)
        self.assertNotIn("PAIN", {item["name"] for item in profile["product_brands"]})
        self.assertFalse(any("✨" in name for name in entity_names))

    def test_context_profile_does_not_use_internal_goal_placeholder(self):
        client = Client(
            id="goal-placeholder",
            user_id="user-1",
            name="PemSpa",
            url="https://pempsa.example",
            industry="boutique skincare spa",
        )
        evidence = {
            "pages": [
                {
                    "url": "https://pempsa.example/services",
                    "title": "Services",
                    "headings": ["Chemical Peel"],
                    "text_blocks": ["Chemical Peel $175 50 minutes"],
                    "json_ld": [],
                    "forms": [],
                }
            ],
            "warnings": [],
        }

        profile, _, _ = build_context_profile(client, evidence)

        self.assertNotIn("Choose the best provider", {item["name"] for item in profile["goals"]})

    def test_legal_pages_and_legalese_locations_are_excluded(self):
        """Terms/legal pages and legalese 'WORD, OR' fragments must never become
        offerings, brands, or locations (the Melius garbage-scan regression)."""
        client = Client(
            id="melius-legal",
            user_id="user-1",
            name="Melius",
            url="https://www.melius.com/",
            industry="AI creative platform",
        )
        evidence = {
            "pages": [
                {
                    "url": "https://www.melius.com/terms",
                    "title": "Melius Terms of Service",
                    "headings": ["2. THE SERVICE", "9. THIRD-PARTY SERVICES AND LINKS"],
                    "text_blocks": [
                        "THE SERVICE WILL MEET YOUR REQUIREMENTS OR EXPECTATIONS",
                        "Gemini Omni Flash",
                        "the service is provided as is, whether STATUTORY, OR USAGE, OR otherwise",
                    ],
                    "json_ld": [],
                    "forms": [],
                },
                {
                    "url": "https://www.melius.com/",
                    "title": "Melius",
                    "headings": ["AI creative canvas"],
                    "text_blocks": ["Node-based multimodal content generation. Based in Boston, MA."],
                    "json_ld": [],
                    "forms": [],
                },
            ],
            "warnings": [],
        }

        profile, _, _ = build_context_profile(client, evidence)
        offerings = {item["name"] for item in profile["offerings"]}
        brands = {item["name"] for item in profile["product_brands"]}
        physical = {item["name"] for item in profile["locations"]["physical_locations"]}

        # Nothing from the Terms page leaked in.
        self.assertFalse(any("STATUTORY" in name for name in offerings | physical))
        self.assertNotIn("Terms of Service", offerings)
        self.assertNotIn("Melius Terms of Service", offerings)
        self.assertFalse(any("Gemini" in name for name in brands))
        # A real city from a content page is still captured cleanly.
        self.assertIn("Boston, MA", physical)


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
                            "competitors": [
                                {"name": "Competitor One", "type": "competitor_business"},
                                {"name": "Competitor One", "type": "competitor_business"},
                                {"name": "Competitor Two", "type": "competitor_business"},
                            ],
                            "locations": {
                                "physical_locations": [],
                                "service_areas": [],
                                "visibility_markets": [],
                                "excluded_locations": [],
                            },
                            "goals": [],
                            "personas": [],
                            "scan_objective": {
                                "optimization_objectives": [
                                    "local_discovery_visibility",
                                    "trust_citation_proof",
                                ],
                                "custom_objective": "Prioritize buyers comparing proof and local availability.",
                            },
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
            client = session.query(Client).filter(Client.id == "client-1").one()
            self.assertIsNotNone(stored.updated_at)
            stored_profile = stored.profile_json
            self.assertEqual(stored_profile["business"]["name"], "AISO Demo")
            self.assertEqual(
                stored_profile["scan_objective"]["optimization_objectives"],
                ["local_discovery_visibility", "trust_citation_proof"],
            )
            self.assertEqual(
                stored_profile["scan_objective"]["custom_objective"],
                "Prioritize buyers comparing proof and local availability.",
            )
            self.assertEqual(client.competitor_names, ["Competitor One", "Competitor Two"])
        finally:
            session.close()

    def test_update_context_rejects_unknown_scan_objectives(self):
        with self.assertRaises(ValidationError):
            ClientContextUpdate(
                status="confirmed",
                profile_json={
                    "business": {"name": "AISO Demo"},
                    "scan_objective": {
                        "optimization_objectives": ["unknown_objective"],
                    },
                },
                warnings_json=[],
            )

    def test_update_context_caps_custom_objective_length(self):
        with self.assertRaises(ValidationError):
            ClientContextUpdate(
                status="confirmed",
                profile_json={
                    "business": {"name": "AISO Demo"},
                    "scan_objective": {
                        "optimization_objectives": [],
                        "custom_objective": "x" * 501,
                    },
                },
                warnings_json=[],
            )


if __name__ == "__main__":
    unittest.main()
