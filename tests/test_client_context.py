import asyncio
import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base, Client, ClientContext, User
from api.routes.client_context import ClientContextUpdate, update_client_context


class ClientContextApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

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
