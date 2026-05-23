import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.adapters.realism_filter import HeuristicRealismFilterAdapter
from api.auth import get_current_user_id
from api.database import Base, BusinessProfile, Client, MethodologyPromptVersion, QuestionCandidate, User, get_db
from api.domain.question_generation import question_text_hash
from api.domain.realism_filter import (
    REALISM_FILTER_PROMPT_KEY,
    REALISM_FILTER_PROMPT_VERSION,
    REALISM_FILTER_SYSTEM_PROMPT,
    REALISM_PASS_THRESHOLD,
)
from api.main import app
from api.routes.onboarding import get_realism_filter_provider


GOOD_QUESTIONS = [
    "what's the best sales CRM for a 50-person B2B SaaS team?",
    "does VectorCRM integrate with Salesforce for pipeline reporting?",
    "VectorCRM vs HubSpot: which is better for RevOps?",
    "what should we ask on a sales CRM demo about implementation?",
    "what is VectorCRM pricing for mid-market SaaS teams?",
    "what do customers say about VectorCRM support?",
    "which CRM tools work best with Slack for sales managers?",
    "what are the best alternatives to Salesforce for forecasting?",
    "should a VP Sales shortlist VectorCRM for lead routing?",
    "how hard is it to migrate from HubSpot to VectorCRM?",
    "is VectorCRM worth it for improving forecast accuracy?",
    "what CRM has the best data quality for SaaS companies?",
    "which sales CRM is easiest for a RevOps Manager to roll out?",
    "how do B2B SaaS teams compare CRM vendors for integrations?",
    "what red flags should we check in VectorCRM reviews?",
    "what should we confirm before signing a VectorCRM contract?",
    "which CRM gives revenue leaders better pipeline visibility?",
    "how can sales teams get more value from VectorCRM after launch?",
    "should we replace Pipedrive with VectorCRM for reporting?",
    "what Salesforce alternatives work well for a 100-person SaaS company?",
]

BAD_QUESTIONS = [
    "Top 10 best CRM software 2026 for B2B SaaS companies?",
    "Best CRM for B2B SaaS companies with 45-55 employees in California?",
    "What's the best for our team?",
    "Tell me about CRM software?",
    "{{brand}} vs {competitor} pricing?",
    "[category] software alternatives?",
    "CRM CRM CRM best best best?",
    "lorem ipsum crm question?",
    "asdf sales tool?",
    "best best best CRM 2026?",
    "what's the best?",
    "n/a?",
    "does <brand> integrate with <tool>?",
    "guaranteed cure sales CRM for teams?",
    "near me near me CRM?",
    "best CRM software software software 2026?",
    "what is the best top 10 CRM?",
    "[object Object] pricing?",
    "XXX CRM comparison?",
    "top 25 CRM platforms in 2026 for 45-55 person SaaS companies?",
]


class Phase12RealismFilterTests(unittest.TestCase):
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
                    personas={"primary": "VP Sales"},
                    crawl_artifacts={},
                    floor_met=True,
                )
            )
            for index, question in enumerate(GOOD_QUESTIONS + BAD_QUESTIONS):
                seed.add(
                    QuestionCandidate(
                        id=f"candidate-{index}",
                        client_id="client-1",
                        text=question,
                        text_hash=question_text_hash(question),
                        journey_stage="J2" if index < len(GOOD_QUESTIONS) else "J1",
                        brand_frame="unbranded_category",
                        intent_class="informational",
                        persona="VP Sales",
                        locality="US",
                        rationale="Acceptance fixture.",
                        generator_version="question_generation-test",
                        realism_filter_version="realism_filter-pending-0.0.0",
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
        app.dependency_overrides[get_realism_filter_provider] = lambda: HeuristicRealismFilterAdapter()
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(get_realism_filter_provider, None)
        self.engine.dispose()

    def test_phase_12_6_acceptance_good_questions_pass_bad_questions_fail(self):
        response = self.client.post("/api/v1/onboarding/client-1/filter-realism")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["evaluated_count"], 40)
        self.assertEqual(payload["prompt_version"], REALISM_FILTER_PROMPT_VERSION)
        self.assertEqual(len(payload["prompt_hash"]), 64)

        db = self.Session()
        try:
            rows = db.query(QuestionCandidate).filter(
                QuestionCandidate.client_id == "client-1",
            ).all()
            by_text = {row.text: row for row in rows}
            good_passed = sum(float(by_text[question].realism_score) >= REALISM_PASS_THRESHOLD for question in GOOD_QUESTIONS)
            bad_failed = sum(float(by_text[question].realism_score) < REALISM_PASS_THRESHOLD for question in BAD_QUESTIONS)
            self.assertGreaterEqual(good_passed, 18)
            self.assertGreaterEqual(bad_failed, 18)
            self.assertTrue(all(row.realism_score is not None for row in rows))
            self.assertTrue(all(row.realism_filter_version.startswith(REALISM_FILTER_PROMPT_VERSION) for row in rows))

            prompt = db.query(MethodologyPromptVersion).filter(
                MethodologyPromptVersion.prompt_key == REALISM_FILTER_PROMPT_KEY,
            ).one()
            self.assertEqual(prompt.version, REALISM_FILTER_PROMPT_VERSION)
            self.assertEqual(prompt.prompt_text, REALISM_FILTER_SYSTEM_PROMPT)
            self.assertEqual(len(prompt.chain_hash), 64)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
