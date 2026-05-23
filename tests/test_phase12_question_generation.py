import unittest
from collections import Counter

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.question_generation import HeuristicQuestionGenerationAdapter
from api.auth import get_current_user_id
from api.database import Base, MethodologyPromptVersion, QuestionCandidate, User, get_db
from api.domain.question_generation import (
    BRAND_FRAMES,
    JOURNEY_STAGES,
    OBJECTIVE_STAGE_WEIGHTS,
    QUESTION_GENERATION_PROMPT_KEY,
    QUESTION_GENERATION_PROMPT_VERSION,
    QUESTION_GENERATION_SYSTEM_PROMPT,
)
from api.main import app
from api.routes.onboarding import get_question_generation_provider


class Phase12QuestionGenerationTests(unittest.TestCase):
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
        app.dependency_overrides[get_question_generation_provider] = lambda: HeuristicQuestionGenerationAdapter()
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(get_question_generation_provider, None)
        self.engine.dispose()

    def test_phase_12_5_acceptance_generates_b2b_saas_candidate_pool(self):
        onboarding_id = self._confirmed_b2b_saas_profile()

        response = self.client.post(
            f"/api/v1/onboarding/{onboarding_id}/generate-questions",
            json={"target_n": 50},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["candidate_count"], 150)
        self.assertEqual(payload["target_n"], 50)
        self.assertEqual(payload["prompt_version"], QUESTION_GENERATION_PROMPT_VERSION)
        self.assertEqual(len(payload["prompt_hash"]), 64)

        db = self.Session()
        try:
            rows = db.query(QuestionCandidate).filter(
                QuestionCandidate.client_id == onboarding_id,
            ).all()
            self.assertEqual(len(rows), 150)
            self.assertEqual(len({row.text_hash for row in rows}), 150)
            self.assertTrue(all(row.generator_version.startswith(QUESTION_GENERATION_PROMPT_VERSION) for row in rows))
            self.assertTrue(all(row.realism_filter_version == "realism_filter-pending-0.0.0" for row in rows))

            stage_counts = Counter(row.journey_stage for row in rows)
            weights = OBJECTIVE_STAGE_WEIGHTS["preference"]
            for stage in JOURNEY_STAGES:
                observed_pct = stage_counts[stage] / len(rows) * 100
                self.assertLessEqual(abs(observed_pct - weights[stage]), 10.0)

            frame_counts = Counter(row.brand_frame for row in rows)
            for frame in BRAND_FRAMES:
                self.assertGreater(frame_counts[frame], 0)

            matrix = Counter((row.journey_stage, row.brand_frame) for row in rows)
            for stage in JOURNEY_STAGES:
                for frame in BRAND_FRAMES:
                    self.assertGreater(matrix[(stage, frame)], 0)

            prompt = db.query(MethodologyPromptVersion).filter(
                MethodologyPromptVersion.prompt_key == QUESTION_GENERATION_PROMPT_KEY,
            ).one()
            self.assertEqual(prompt.version, QUESTION_GENERATION_PROMPT_VERSION)
            self.assertEqual(prompt.prompt_text, QUESTION_GENERATION_SYSTEM_PROMPT)
            self.assertEqual(len(prompt.chain_hash), 64)
        finally:
            db.close()

    def _confirmed_b2b_saas_profile(self) -> str:
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
        confirmed = self.client.post(
            f"/api/v1/onboarding/{onboarding_id}/confirm-profile",
            json={
                "category": "sales CRM",
                "industry": "B2B SaaS",
                "employee_band": "51-200",
                "revenue_band": "$10M-$50M",
                "firmographic_geography": "United States",
                "acv_band": "$25k-$50k",
                "primary_persona": "VP Sales",
                "economic_buyer": "Chief Revenue Officer",
                "end_user": "RevOps Manager",
                "geographic_scope": {"countries": ["US"]},
                "competitors": ["HubSpot", "Salesforce", "Pipedrive"],
                "crawl_artifacts": {
                    "auto_extracted": {
                        "brand_name": "VectorCRM",
                        "product_service_taxonomy": ["sales CRM"],
                    }
                },
            },
        )
        self.assertEqual(confirmed.status_code, 200)
        return onboarding_id


if __name__ == "__main__":
    unittest.main()
