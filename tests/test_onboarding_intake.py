import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth import get_current_user_id
from api.database import Base, BusinessProfile, Client, User, get_db
from api.main import app


class OnboardingIntakeAPITests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        seed = self.Session()
        try:
            seed.add(User(id="user-1", email="founder@example.com"))
            seed.commit()
        finally:
            seed.close()

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user_id] = lambda: "user-1"
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_id, None)
        self.engine.dispose()

    def test_phase_12_1_acceptance_start_patch_submit_context_floor(self):
        start = self.client.post(
            "/api/v1/onboarding/start",
            json={
                "display_name": "Acme CRM",
                "url": "https://acme.example",
                "vertical": "b2b_saas",
                "objective": "preference",
            },
        )
        self.assertEqual(start.status_code, 201)
        start_data = start.json()
        onboarding_id = start_data["onboarding_id"]
        self.assertEqual(start_data["client_id"], onboarding_id)
        self.assertFalse(start_data["floor_met"])

        incomplete = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(incomplete.status_code, 400)
        incomplete_detail = incomplete.json()["detail"]
        self.assertEqual(incomplete_detail["error"], "ContextFloorNotMet")
        self.assertIn("category", incomplete_detail["missing_fields"])
        self.assertIn("competitors", incomplete_detail["missing_fields"])

        patch_steps = [
            {"category": "sales intelligence CRM"},
            {"industry": "B2B SaaS"},
            {"employee_band": "51-200"},
            {"revenue_band": "$10M-$50M"},
            {"firmographic_geography": "United States"},
            {"acv_band": "$25k-$50k"},
            {"primary_persona": "VP Sales"},
            {"geographic_scope": {"countries": ["US"]}},
            {"competitors": ["HubSpot", "Salesforce"]},
        ]
        for step in patch_steps:
            patched = self.client.patch(f"/api/v1/onboarding/{onboarding_id}", json=step)
            self.assertEqual(patched.status_code, 200)

        two_competitors = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(two_competitors.status_code, 400)
        self.assertIn("competitors", two_competitors.json()["detail"]["missing_fields"])

        final_patch = self.client.patch(
            f"/api/v1/onboarding/{onboarding_id}",
            json={"competitors": ["HubSpot", "Salesforce", "Pipedrive"]},
        )
        self.assertEqual(final_patch.status_code, 200)

        submitted = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(submitted.status_code, 200)
        submitted_data = submitted.json()
        self.assertTrue(submitted_data["ok"])
        self.assertTrue(submitted_data["floor_met"])
        self.assertEqual(submitted_data["missing_fields"], [])

        db = self.Session()
        try:
            self.assertEqual(db.query(Client).count(), 1)
            profile = db.query(BusinessProfile).filter(BusinessProfile.client_id == onboarding_id).one()
            self.assertTrue(profile.floor_met)
            self.assertIsNotNone(profile.onboarding_completed_at)
            self.assertEqual(profile.competitors, ["HubSpot", "Salesforce", "Pipedrive"])
            self.assertEqual(profile.icp["firmographics"]["employee_band"], "51-200")
            self.assertEqual(profile.personas["primary"], "VP Sales")
        finally:
            db.close()

    def test_phase_12_2_serves_starting_vertical_intake_schemas(self):
        for vertical in ("b2b_saas", "local_services", "ecommerce"):
            response = self.client.get(f"/api/v1/onboarding/intake-schemas/{vertical}")
            self.assertEqual(response.status_code, 200)
            schema = response.json()
            self.assertEqual(schema["vertical"], vertical)
            self.assertGreaterEqual(len(schema["fields"]), 3)
            self.assertTrue(schema["required_fields"])
            self.assertTrue(
                all(
                    {"id", "label", "type", "required", "patch_field"}.issubset(field)
                    for field in schema["fields"]
                )
            )

    def test_phase_12_2_b2b_saas_required_fields_are_enforced(self):
        start = self.client.post(
            "/api/v1/onboarding/start",
            json={
                "display_name": "Schema CRM",
                "url": "https://schema.example",
                "vertical": "b2b_saas",
                "objective": "preference",
            },
        )
        self.assertEqual(start.status_code, 201)
        onboarding_id = start.json()["onboarding_id"]

        partial = self.client.patch(
            f"/api/v1/onboarding/{onboarding_id}",
            json={
                "category": "sales CRM",
                "industry": "B2B SaaS",
                "employee_band": "51-200",
                "revenue_band": "$10M-$50M",
                "firmographic_geography": "United States",
                "acv_band": "$25k-$50k",
                "primary_persona": "VP Sales",
                "geographic_scope_description": "United States",
                "competitors": ["HubSpot", "Salesforce"],
            },
        )
        self.assertEqual(partial.status_code, 200)

        blocked = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.json()["detail"]["error"], "ContextFloorNotMet")
        self.assertIn("competitors", blocked.json()["detail"]["missing_fields"])

        completed = self.client.patch(
            f"/api/v1/onboarding/{onboarding_id}",
            json={"competitors": ["HubSpot", "Salesforce", "Pipedrive"]},
        )
        self.assertEqual(completed.status_code, 200)
        submitted = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(submitted.status_code, 200)
        self.assertTrue(submitted.json()["floor_met"])


if __name__ == "__main__":
    unittest.main()
