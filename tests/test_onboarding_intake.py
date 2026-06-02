import unittest
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth import get_current_user_id
from api.database import Base, BusinessProfile, Client, MethodologyPromptVersion, User, get_db
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
        self.assertEqual(UUID(onboarding_id, version=4).version, 4)
        self.assertFalse(start_data["floor_met"])

        incomplete = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(incomplete.status_code, 400)
        incomplete_detail = incomplete.json()["detail"]
        self.assertEqual(incomplete_detail["error"], "ContextFloorNotMet")
        self.assertIn("category", incomplete_detail["missing_fields"])
        self.assertNotIn("competitors", incomplete_detail["missing_fields"])

        patch_steps = [
            {"category": "sales intelligence CRM"},
            {"industry": "B2B SaaS"},
            {"employee_band": "51-200"},
            {"revenue_band": "$10M-$50M"},
            {"firmographic_geography": "United States"},
            {"acv_band": "$25k-$50k"},
            {"primary_persona": "VP Sales"},
            {"geographic_scope": {"countries": ["US"]}},
        ]
        for step in patch_steps:
            patched = self.client.patch(f"/api/v1/onboarding/{onboarding_id}", json=step)
            self.assertEqual(patched.status_code, 200)

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
            self.assertEqual(profile.competitors, [])
            self.assertEqual(profile.icp["firmographics"]["employee_band"], "51-200")
            self.assertEqual(profile.personas["primary"], "VP Sales")
        finally:
            db.close()

    def test_onboarding_start_rejects_slug_client_id(self):
        start = self.client.post(
            "/api/v1/onboarding/start",
            json={
                "client_id": "sapienic",
                "display_name": "Sapienic",
                "url": "https://sapienic.example",
                "vertical": "b2b_saas",
                "objective": "consideration",
            },
        )
        self.assertEqual(start.status_code, 422)
        self.assertEqual(start.json()["detail"], "client_id must be a UUIDv4")

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
            },
        )
        self.assertEqual(partial.status_code, 200)

        submitted = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(submitted.status_code, 200)
        self.assertTrue(submitted.json()["floor_met"])

    def test_local_services_competitors_and_license_are_optional_but_working_hours_required(self):
        start = self.client.post(
            "/api/v1/onboarding/start",
            json={
                "display_name": "Glow Day Spa",
                "url": "https://glow.example",
                "vertical": "local_services",
                "objective": "consideration",
            },
        )
        self.assertEqual(start.status_code, 201)
        onboarding_id = start.json()["onboarding_id"]

        partial = self.client.patch(
            f"/api/v1/onboarding/{onboarding_id}",
            json={
                "category": "day spa",
                "nap": "Glow Day Spa | 123 Main St, Boston, MA 02118 | (617) 555-0100",
                "service_radius": "10 miles around Boston",
                "service_taxonomy": ["facials", "massage", "waxing"],
            },
        )
        self.assertEqual(partial.status_code, 200)

        blocked = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(blocked.status_code, 400)
        missing = blocked.json()["detail"]["missing_fields"]
        self.assertIn("geographic_scope.hours", missing)
        self.assertNotIn("competitors", missing)
        self.assertNotIn("icp.license_cert_numbers", missing)

        completed = self.client.patch(
            f"/api/v1/onboarding/{onboarding_id}",
            json={"hours": "Mon-Fri 9am-7pm, Sat 10am-5pm"},
        )
        self.assertEqual(completed.status_code, 200)
        submitted = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(submitted.status_code, 200)
        self.assertTrue(submitted.json()["floor_met"])

    def test_phase_12_4_drafts_profile_from_crawl_artifacts_and_flags_human_fields(self):
        start = self.client.post(
            "/api/v1/onboarding/start",
            json={
                "display_name": "VectorCRM",
                "url": "https://vector.example",
                "vertical": "b2b_saas",
                "objective": "preference",
            },
        )
        self.assertEqual(start.status_code, 201)
        onboarding_id = start.json()["onboarding_id"]

        crawl_artifacts = {
            "schema_version": "crawl_artifacts.v1",
            "auto_extracted": {
                "brand_name": "VectorCRM",
                "product_service_taxonomy": ["AI Search Monitoring"],
                "nap": {
                    "name": "VectorCRM",
                    "address": {"addressLocality": "Boston", "addressRegion": "MA"},
                    "source_url": "https://vector.example",
                },
                "schema_entity_types": ["Organization", "Service"],
            },
            "structured_data": {
                "Organization": [{"name": "VectorCRM", "source_url": "https://vector.example"}],
                "Service": [{"name": "AI Search Monitoring", "source_url": "https://vector.example"}],
            },
        }
        patched = self.client.patch(
            f"/api/v1/onboarding/{onboarding_id}",
            json={"crawl_artifacts": crawl_artifacts},
        )
        self.assertEqual(patched.status_code, 200)

        drafted = self.client.post(f"/api/v1/onboarding/{onboarding_id}/draft-profile")
        self.assertEqual(drafted.status_code, 200)
        draft = drafted.json()
        self.assertEqual(draft["category"], "AI Search Monitoring")
        self.assertEqual(draft["field_flags"]["category"], "crawled")
        self.assertEqual(draft["field_flags"]["geographic_scope"], "crawled")
        self.assertEqual(draft["field_flags"]["icp"], "needs_you")
        self.assertEqual(draft["field_flags"]["competitors"], "needs_you")
        self.assertEqual(draft["field_flags"]["objective"], "needs_you")
        self.assertEqual(draft["geographic_scope"]["nap"]["address"]["addressLocality"], "Boston")

        db = self.Session()
        try:
            prompt = db.query(MethodologyPromptVersion).filter(
                MethodologyPromptVersion.prompt_key == "profile_draft",
            ).one()
            self.assertEqual(prompt.version, "profile_draft-1.0.0")
            self.assertEqual(len(prompt.prompt_hash), 64)
            self.assertEqual(len(prompt.chain_hash), 64)
            profile = db.query(BusinessProfile).filter(BusinessProfile.client_id == onboarding_id).one()
            self.assertEqual(profile.crawl_artifacts["profile_draft"]["field_sources"]["objective"], "needs_you")
        finally:
            db.close()

    def test_phase_12_4_customer_edits_and_confirms_profile(self):
        start = self.client.post(
            "/api/v1/onboarding/start",
            json={
                "display_name": "Confirm CRM",
                "url": "https://confirm.example",
                "vertical": "b2b_saas",
                "objective": "preference",
            },
        )
        self.assertEqual(start.status_code, 201)
        onboarding_id = start.json()["onboarding_id"]

        self.client.patch(
            f"/api/v1/onboarding/{onboarding_id}",
            json={
                "category": "sales CRM",
                "geographic_scope": {"countries": ["US"]},
                "crawl_artifacts": {
                    "auto_extracted": {"product_service_taxonomy": ["sales CRM"]},
                    "profile_draft": {"field_sources": {"competitors": "needs_you"}},
                },
            },
        )
        confirmed = self.client.post(
            f"/api/v1/onboarding/{onboarding_id}/confirm-profile",
            json={
                "industry": "B2B SaaS",
                "employee_band": "51-200",
                "revenue_band": "$10M-$50M",
                "firmographic_geography": "United States",
                "acv_band": "$25k-$50k",
                "primary_persona": "VP Sales",
                "competitors": ["HubSpot", "Salesforce", "Pipedrive"],
            },
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(confirmed.json()["floor_met"])

        db = self.Session()
        try:
            profile = db.query(BusinessProfile).filter(BusinessProfile.client_id == onboarding_id).one()
            self.assertTrue(profile.floor_met)
            self.assertIsNotNone(profile.onboarding_completed_at)
            self.assertEqual(profile.crawl_artifacts["profile_confirmation"]["actor"], "customer")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
