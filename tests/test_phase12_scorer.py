import unittest
import json
from decimal import Decimal, ROUND_HALF_UP

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.question_scorer import HeuristicQuestionScorerAdapter
from api.auth import get_current_user_id
from api.database import Base, BusinessProfile, Client, MethodologyPromptVersion, QuestionCandidate, QuestionScore, User, get_db
from api.domain.question_generation import question_text_hash
from api.domain.ports import ProviderResponse
from api.domain.question_scorer import (
    QUESTION_SCORER_PROMPT_KEY,
    QUESTION_SCORER_PROMPT_VERSION,
    SCORE_WEIGHTS,
    scorer_prompt_text_for_registry,
)
from api.main import app
from api.routes.onboarding import get_question_scorer_provider


SCORER_FIXTURE_QUESTIONS = [
    ("what's the best sales CRM for a 50-person B2B SaaS team?", "J1", "unbranded_category", "informational"),
    ("does VectorCRM integrate with Salesforce for pipeline reporting?", "J2", "brand_only", "informational"),
    ("VectorCRM vs HubSpot: which is better for RevOps?", "J3", "branded_comparison", "informational"),
    ("what should we ask on a sales CRM demo about implementation?", "J4", "unbranded_category", "transactional"),
    ("what is VectorCRM pricing for mid-market SaaS teams?", "J4", "brand_only", "transactional"),
    ("what do customers say about VectorCRM support?", "J5", "brand_only", "navigational"),
    ("which CRM tools work best with Slack for sales managers?", "J2", "unbranded_category", "informational"),
    ("what are the best alternatives to Salesforce for forecasting?", "J3", "competitor_only", "informational"),
    ("should a VP Sales shortlist VectorCRM for lead routing?", "J2", "brand_only", "informational"),
    ("how hard is it to migrate from HubSpot to VectorCRM?", "J6", "branded_comparison", "transactional"),
    ("is VectorCRM worth it for improving forecast accuracy?", "J4", "brand_only", "transactional"),
    ("what CRM has the best data quality for SaaS companies?", "J2", "unbranded_category", "informational"),
    ("which sales CRM is easiest for a RevOps Manager to roll out?", "J3", "unbranded_category", "informational"),
    ("how do B2B SaaS teams compare CRM vendors for integrations?", "J2", "unbranded_category", "informational"),
    ("what red flags should we check in VectorCRM reviews?", "J5", "brand_only", "navigational"),
    ("what should we confirm before signing a VectorCRM contract?", "J4", "brand_only", "transactional"),
    ("which CRM gives revenue leaders better pipeline visibility?", "J2", "unbranded_category", "informational"),
    ("how can sales teams get more value from VectorCRM after launch?", "J6", "brand_only", "transactional"),
    ("should we replace Pipedrive with VectorCRM for reporting?", "J6", "branded_comparison", "transactional"),
    ("what Salesforce alternatives work well for a 100-person SaaS company?", "J3", "competitor_only", "informational"),
]


class LowAgreementQuestionScorerAdapter:
    provider = "local"
    model = "question-scorer-low-agreement-test"

    def complete(
        self,
        *,
        prompt: str,
        seed: int,
        temperature: float,
        idempotency_key: str,
    ) -> ProviderResponse:
        run_index = int(idempotency_key.rsplit(":", 1)[-1])
        score = [1.0, 5.0, 10.0][run_index]
        response = {
            "scores": {
                "D1": score,
                "D2": score,
                "D3": {"a": score, "b": score, "c": score, "d": score, "mean": score},
                "D4": score,
                "D5": score,
            },
            "rationale": "Intentionally divergent scorer fixture.",
        }
        return ProviderResponse(
            text=json.dumps(response, sort_keys=True),
            provider=self.provider,
            model=self.model,
            raw_metadata={"seed": seed, "temperature": temperature},
        )


class Phase12ScorerTests(unittest.TestCase):
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
                    icp={
                        "firmographics": {
                            "industry": "B2B SaaS",
                            "employee_band": "51-200",
                            "revenue_band": "$10M-$50M",
                            "geography": "United States",
                        },
                        "acv_band": "$25k-$50k",
                    },
                    geographic_scope={"countries": ["US"]},
                    competitors=["HubSpot", "Salesforce", "Pipedrive"],
                    personas={"primary": "VP Sales", "economic_buyer": "CRO"},
                    crawl_artifacts={"auto_extracted": {"brand_name": "VectorCRM"}},
                    floor_met=True,
                )
            )
            for index, (question, stage, frame, intent) in enumerate(SCORER_FIXTURE_QUESTIONS):
                seed.add(
                    QuestionCandidate(
                        id=f"candidate-{index}",
                        client_id="client-1",
                        text=question,
                        text_hash=question_text_hash(question),
                        journey_stage=stage,
                        brand_frame=frame,
                        intent_class=intent,
                        persona="VP Sales",
                        locality="US",
                        rationale="Acceptance fixture.",
                        realism_score=Decimal("8.000"),
                        generator_version="question_generation-test",
                        realism_filter_version="realism_filter-test",
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
        app.dependency_overrides[get_question_scorer_provider] = lambda: HeuristicQuestionScorerAdapter()
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(get_question_scorer_provider, None)
        self.engine.dispose()

    def test_phase_12_7_acceptance_scores_20_candidates_with_weighted_formula(self):
        response = self.client.post("/api/v1/onboarding/client-1/score-questions", json={"limit": 20})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["evaluated_count"], 20)
        self.assertEqual(payload["scored_count"], 20)
        self.assertEqual(payload["human_review_count"], 0)
        self.assertEqual(payload["human_review_question_ids"], [])
        self.assertEqual(payload["prompt_version"], QUESTION_SCORER_PROMPT_VERSION)
        self.assertEqual(len(payload["prompt_hash"]), 64)
        self.assertGreaterEqual(payload["min_gwet_ac2"], payload["agreement_threshold"])

        db = self.Session()
        try:
            rows = db.query(QuestionScore).all()
            self.assertEqual(len(rows), 20)
            for row in rows:
                self.assertIsNotNone(row.d1_buyer_plausibility)
                self.assertIsNotNone(row.d2_commercial_proximity)
                self.assertIsNotNone(row.d3_cognitive_answerability)
                self.assertIsNotNone(row.d4_diagnostic_power)
                self.assertIsNotNone(row.d5_statistical_identifiability)
                expected = (
                    Decimal(str(SCORE_WEIGHTS["D1"])) * row.d1_buyer_plausibility
                    + Decimal(str(SCORE_WEIGHTS["D2"])) * row.d2_commercial_proximity
                    + Decimal(str(SCORE_WEIGHTS["D3"])) * row.d3_cognitive_answerability
                    + Decimal(str(SCORE_WEIGHTS["D4"])) * row.d4_diagnostic_power
                    + Decimal(str(SCORE_WEIGHTS["D5"])) * row.d5_statistical_identifiability
                ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                self.assertEqual(expected, row.weighted_score)

            prompt = db.query(MethodologyPromptVersion).filter(
                MethodologyPromptVersion.prompt_key == QUESTION_SCORER_PROMPT_KEY,
            ).one()
            self.assertEqual(prompt.version, QUESTION_SCORER_PROMPT_VERSION)
            self.assertEqual(prompt.prompt_text, scorer_prompt_text_for_registry())
            self.assertEqual(len(prompt.chain_hash), 64)
        finally:
            db.close()

    def test_low_ac2_flags_candidate_for_human_review_without_persisting_score(self):
        app.dependency_overrides[get_question_scorer_provider] = lambda: LowAgreementQuestionScorerAdapter()

        response = self.client.post("/api/v1/onboarding/client-1/score-questions", json={"limit": 1})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["evaluated_count"], 1)
        self.assertEqual(payload["scored_count"], 0)
        self.assertEqual(payload["human_review_count"], 1)
        self.assertEqual(payload["human_review_question_ids"], ["candidate-0"])
        self.assertLess(payload["min_gwet_ac2"], payload["agreement_threshold"])

        db = self.Session()
        try:
            self.assertEqual(db.query(QuestionScore).count(), 0)
            candidate = db.query(QuestionCandidate).filter(QuestionCandidate.id == "candidate-0").one()
            self.assertIn("scorer_human_review_required", candidate.rationale or "")
            self.assertIn("gwet_ac2=", candidate.rationale or "")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
