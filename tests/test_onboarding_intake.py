import unittest
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from api.auth import get_current_user_id
from api.database import Base, BusinessProfile, Client, MethodologyPromptVersion, User, get_db
from api.domain.onboarding import VERTICAL_CODES, VERTICAL_DISPLAY_ORDER
from api.main import app
from tests._pgharness import make_test_engine, reset_schema


class OnboardingIntakeAPITests(unittest.TestCase):
    def setUp(self):
        # SQLite by default; real Postgres (FK-enforced) when TEST_DATABASE_URL is set.
        self.engine = make_test_engine()
        reset_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)

        seed = self.Session()
        try:
            # custom tier: these tests onboard many businesses under one user,
            # which only the unlimited (custom) tier permits.
            seed.add(User(id="user-1", email="founder@example.com", plan_tier="custom"))
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

    def test_start_inserts_client_before_business_profile(self):
        statements: list[str] = []

        def record_insert_order(conn, cursor, statement, parameters, context, executemany):
            normalized = statement.strip().lower()
            if normalized.startswith("insert into clients"):
                statements.append("clients")
            if normalized.startswith("insert into business_profile"):
                statements.append("business_profile")

        event.listen(self.engine, "before_cursor_execute", record_insert_order)
        try:
            start = self.client.post(
                "/api/v1/onboarding/start",
                json={
                    "client_id": "ordered_insert_client",
                    "display_name": "Ordered Insert Co",
                    "url": "https://ordered.example",
                    "vertical": "b2b_saas",
                    "objective": "preference",
                },
            )
            self.assertEqual(start.status_code, 201)
            self.assertEqual(statements[:2], ["clients", "business_profile"])
        finally:
            event.remove(self.engine, "before_cursor_execute", record_insert_order)

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

    def test_phase_12_2_serves_all_supported_vertical_intake_schemas(self):
        for vertical in sorted(VERTICAL_CODES):
            response = self.client.get(f"/api/v1/onboarding/intake-schemas/{vertical}")
            self.assertEqual(response.status_code, 200)
            schema = response.json()
            self.assertEqual(schema["vertical"], vertical)
            self.assertGreaterEqual(len(schema["fields"]), 3)
            self.assertTrue(schema["required_fields"])
            self.assertEqual(
                set(schema["required_fields"]),
                {field["id"] for field in schema["fields"] if field["required"]},
            )
            self.assertTrue(
                all(
                    {"id", "label", "type", "required", "patch_field"}.issubset(field)
                    for field in schema["fields"]
                )
            )

    def test_intake_vertical_metadata_is_schema_backed_and_ordered(self):
        response = self.client.get("/api/v1/onboarding/intake-verticals")
        self.assertEqual(response.status_code, 200)
        verticals = response.json()
        self.assertEqual([vertical["id"] for vertical in verticals], list(VERTICAL_DISPLAY_ORDER))

        for vertical in verticals:
            with self.subTest(vertical=vertical["id"]):
                schema = self.client.get(f"/api/v1/onboarding/intake-schemas/{vertical['id']}").json()
                self.assertEqual(vertical["label"], schema["label"])
                self.assertEqual(vertical["description"], schema["description"])
                self.assertTrue(vertical.get("example"))

    def test_minimal_context_floor_is_category_and_objective(self):
        # Lean floor: every vertical needs only a category + an objective. The old
        # per-vertical firmographics/hours/etc. requirements are gone - AISO drafts
        # them from the site and the user confirms.
        from api.domain.onboarding import context_floor_met, missing_context_fields
        from api.domain.ports import BusinessProfileSnapshot

        for vertical in ("b2b_saas", "local_services", "consumer_brand", "marketplace", "agency", "enterprise"):
            met = BusinessProfileSnapshot(
                client_id="c", vertical=vertical, objective="consideration", category="a category",
            )
            self.assertEqual(missing_context_fields(met), [], vertical)
            self.assertTrue(context_floor_met(met), vertical)
            self.assertIn("category", missing_context_fields(
                BusinessProfileSnapshot(client_id="c", vertical=vertical, objective="consideration", category="")))
            self.assertIn("objective", missing_context_fields(
                BusinessProfileSnapshot(client_id="c", vertical=vertical, objective="", category="a category")))

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

    def test_repeat_scan_can_load_saved_onboarding_profile(self):
        start = self.client.post(
            "/api/v1/onboarding/start",
            json={
                "display_name": "Repeat Scan Co",
                "url": "https://repeat.example",
                "vertical": "consumer_brand",
                "objective": "consideration",
            },
        )
        self.assertEqual(start.status_code, 201)
        onboarding_id = start.json()["onboarding_id"]

        patched = self.client.patch(
            f"/api/v1/onboarding/{onboarding_id}",
            json={
                "category": "general merchandise retail",
                "brand_archetype": "General merchandise retailer",
                "product_line_breadth": "Household essentials, apparel, groceries",
                "price_tier": "Mixed",
                "distribution_channels": ["Stores", "Website", "Mobile app"],
                "target": "Value-conscious families",
                "geographic_scope_description": "United States",
                "competitors": ["Competitor A", "Competitor B"],
            },
        )
        self.assertEqual(patched.status_code, 200)
        submitted = self.client.post(f"/api/v1/onboarding/{onboarding_id}/submit")
        self.assertEqual(submitted.status_code, 200)

        loaded = self.client.get(f"/api/v1/onboarding/{onboarding_id}")
        self.assertEqual(loaded.status_code, 200)
        profile = loaded.json()
        self.assertEqual(profile["client_id"], onboarding_id)
        self.assertEqual(profile["vertical"], "consumer_brand")
        self.assertEqual(profile["objective"], "consideration")
        self.assertTrue(profile["floor_met"])
        self.assertEqual(profile["icp"]["brand_archetype"], "General merchandise retailer")
        self.assertEqual(profile["icp"]["distribution_channels"], ["Stores", "Website", "Mobile app"])
        self.assertEqual(profile["geographic_scope"]["description"], "United States")
        self.assertEqual(profile["competitors"], ["Competitor A", "Competitor B"])

    def test_local_services_confirms_with_category_and_objective(self):
        # Lean floor: local services now needs only a category + objective. Hours,
        # competitors, license, etc. are optional (AISO drafts + user confirms).
        start = self.client.post(
            "/api/v1/onboarding/start",
            json={
                "display_name": "Anchor Repair",
                "url": "https://anchor.example",
                "vertical": "local_services",
                "objective": "consideration",
            },
        )
        self.assertEqual(start.status_code, 201)
        onboarding_id = start.json()["onboarding_id"]

        patched = self.client.patch(
            f"/api/v1/onboarding/{onboarding_id}",
            json={"category": "home repair service"},
        )
        self.assertEqual(patched.status_code, 200)

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
