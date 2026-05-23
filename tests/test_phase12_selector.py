import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth import get_current_user_id
from api.database import Base, BusinessProfile, Client, QuestionCandidate, QuestionScore, User, get_db
from api.domain.question_generation import BRAND_FRAMES, INTENT_CLASSES, JOURNEY_STAGES, question_text_hash
from api.domain.question_selection import (
    DEFAULT_FRAME_MIN,
    DEFAULT_INTENT_BAND,
    DEFAULT_JOURNEY_MIN,
    OBJECTIVE_STAGE_WEIGHTS,
    objective_stage_targets,
)
from api.main import app


class Phase12SelectorTests(unittest.TestCase):
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
            seed.add(Client(id="client-1", user_id="user-1", name="VectorCRM", url="https://vector.example"))
            seed.add(
                BusinessProfile(
                    client_id="client-1",
                    vertical="b2b_saas",
                    objective="preference",
                    category="sales CRM",
                    icp={"firmographics": {"industry": "B2B SaaS", "employee_band": "51-200"}},
                    geographic_scope={"countries": ["US"]},
                    competitors=["HubSpot", "Salesforce", "Pipedrive"],
                    personas={"primary": "VP Sales", "economic_buyer": "CRO"},
                    crawl_artifacts={"auto_extracted": {"brand_name": "VectorCRM"}},
                    floor_met=True,
                )
            )
            scored_at = datetime.now(timezone.utc)
            for index in range(150):
                stage = JOURNEY_STAGES[index % len(JOURNEY_STAGES)]
                frame = BRAND_FRAMES[(index // len(JOURNEY_STAGES)) % len(BRAND_FRAMES)]
                intent = INTENT_CLASSES[(index // (len(JOURNEY_STAGES) * len(BRAND_FRAMES))) % len(INTENT_CLASSES)]
                persona = "VP Sales" if index % 2 == 0 else "CRO"
                question = (
                    f"what should {persona} evaluate for VectorCRM use case {index} "
                    f"at {stage} with {frame} and {intent} intent?"
                )
                candidate = QuestionCandidate(
                    id=f"candidate-{index}",
                    client_id="client-1",
                    text=question,
                    text_hash=question_text_hash(question),
                    journey_stage=stage,
                    brand_frame=frame,
                    intent_class=intent,
                    persona=persona,
                    locality="US",
                    rationale="Selector acceptance fixture.",
                    realism_score=Decimal("8.000"),
                    selected=index < 3,
                    generator_version="question_generation-test",
                    realism_filter_version="realism_filter-test",
                )
                seed.add(candidate)
                score = Decimal("9.500") - Decimal(index % 40) * Decimal("0.050")
                seed.add(
                    QuestionScore(
                        question_id=candidate.id,
                        scored_at=scored_at + timedelta(milliseconds=index),
                        d1_buyer_plausibility=score,
                        d2_commercial_proximity=score,
                        d3_cognitive_answerability=score,
                        d4_diagnostic_power=score,
                        d5_statistical_identifiability=score,
                        weighted_score=score,
                        rationale="Acceptance score.",
                        scorer_version="question_scorer-test",
                    )
                )
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

    def test_phase_12_8_acceptance_selects_50_with_default_constraints(self):
        critical_ids = ["candidate-145", "candidate-146", "candidate-147"]
        response = self.client.post(
            "/api/v1/onboarding/client-1/select-questions",
            json={"target_n": 50, "critical_question_ids": critical_ids},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["selected_count"], 50)
        self.assertEqual(len(payload["selected_question_ids"]), 50)
        self.assertEqual(payload["objective"], "preference")
        self.assertEqual(payload["objective_journey_targets"], objective_stage_targets("preference", 50))
        self.assertLess(payload["solver_seconds"], 2.0)
        self.assertTrue(set(critical_ids).issubset(set(payload["selected_question_ids"])))
        self.assertEqual(
            OBJECTIVE_STAGE_WEIGHTS["preference"],
            {"J1": 5, "J2": 15, "J3": 20, "J4": 35, "J5": 20, "J6": 5},
        )

        for stage, minimum in DEFAULT_JOURNEY_MIN.items():
            self.assertGreaterEqual(payload["journey_distribution"].get(stage, 0), minimum)
        for frame, minimum in DEFAULT_FRAME_MIN.items():
            self.assertGreaterEqual(payload["frame_distribution"].get(frame, 0), minimum)
        for intent, (lo, hi) in DEFAULT_INTENT_BAND.items():
            count = payload["intent_distribution"].get(intent, 0)
            self.assertGreaterEqual(count, lo * 50)
            self.assertLessEqual(count, hi * 50)
        self.assertGreaterEqual(payload["persona_distribution"].get("VP Sales", 0), 1)
        self.assertGreaterEqual(payload["persona_distribution"].get("CRO", 0), 1)

        db = self.Session()
        try:
            self.assertEqual(db.query(QuestionCandidate).filter(QuestionCandidate.client_id == "client-1").count(), 150)
            selected_rows = db.query(QuestionCandidate).filter(
                QuestionCandidate.client_id == "client-1",
                QuestionCandidate.selected.is_(True),
            ).all()
            self.assertEqual(len(selected_rows), 50)
            self.assertEqual({row.id for row in selected_rows}, set(payload["selected_question_ids"]))
        finally:
            db.close()

    def test_phase_12_8_infeasible_constraints_name_the_violated_constraint(self):
        response = self.client.post(
            "/api/v1/onboarding/client-1/select-questions",
            json={"target_n": 50, "journey_min": {"J1": 151}},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("journey_min[J1]", response.json()["detail"])
        self.assertIn("requires 151", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
