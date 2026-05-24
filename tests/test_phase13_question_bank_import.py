from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base, Client, QuestionCandidate, QuestionScore, ScanManifest, User
from api.domain.question_bank import (
    BANK_FRAME_BRAND,
    BANK_FRAME_COMPARISON,
    BANK_FRAME_UNBRANDED,
    QuestionWeightInput,
    canonical_brand_frame,
    evidence_weight,
    initial_core_count,
    normalized_journey_weights,
    normalized_question_weights,
    raw_question_weight,
)
from api.domain.question_generation import question_text_hash
from api.question_gen.question_bank import QuestionBankImportError, import_selected_questions_to_question_bank


class Phase13QuestionBankImportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_maps_phase12_brand_frames_to_question_bank_frames(self):
        self.assertEqual(canonical_brand_frame("unbranded_category"), BANK_FRAME_UNBRANDED)
        self.assertEqual(canonical_brand_frame("brand_only"), BANK_FRAME_BRAND)
        self.assertEqual(canonical_brand_frame("branded_comparison"), BANK_FRAME_COMPARISON)
        self.assertEqual(canonical_brand_frame("competitor_only"), BANK_FRAME_COMPARISON)

    def test_initial_bank_uses_seventy_percent_core_questions(self):
        self.assertEqual(initial_core_count(50), 35)

    def test_normalized_journey_weights_sum_to_target_n(self):
        weights = normalized_journey_weights(
            ["J1", "J2", "J3", "J4", "J5", "J6"] * 8 + ["J1", "J2"],
            target_total=50,
        )

        self.assertEqual(len(weights), 50)
        self.assertEqual(sum(weights, Decimal("0")), Decimal("50.0000"))
        self.assertTrue(all(weight > 0 for weight in weights))

    def test_full_question_weight_factors_are_applied_and_normalized(self):
        high_value = QuestionWeightInput(
            question_id="q-high",
            journey_stage="J2",
            brand_frame=BANK_FRAME_COMPARISON,
            vertical="b2b_saas",
            answer_stability=Decimal("10.000"),
            critical=True,
        )
        low_value = QuestionWeightInput(
            question_id="q-low",
            journey_stage="J6",
            brand_frame=BANK_FRAME_BRAND,
            vertical="b2b_saas",
            answer_stability=Decimal("3.000"),
        )

        self.assertEqual(evidence_weight(Decimal("10.000")), Decimal("1.00"))
        self.assertEqual(evidence_weight(Decimal("0.000")), Decimal("0.30"))
        self.assertGreater(raw_question_weight(high_value), raw_question_weight(low_value))

        weights = normalized_question_weights([high_value, low_value], target_total=2)
        self.assertEqual(sum(weights, Decimal("0")), Decimal("2.0000"))
        self.assertGreater(weights[0], weights[1])

    def test_question_weight_override_caps_are_enforced(self):
        inputs = [
            QuestionWeightInput(
                question_id=f"q-{index}",
                journey_stage="J2",
                brand_frame=BANK_FRAME_UNBRANDED,
                critical=True,
            )
            for index in range(3)
        ]

        with self.assertRaises(ValueError):
            normalized_question_weights(inputs, target_total=3)

    def test_existing_manifest_retry_rejects_changed_selected_portfolio(self):
        session = self.Session()
        try:
            rows = self._seed_import_fixture(session, count=3)
            selected_at = datetime.now(timezone.utc)
            import_selected_questions_to_question_bank(
                session,
                client_id="client-1",
                scan_id="scan-1",
                selected_at=selected_at,
                rows=rows[:2],
                vertical="b2b_saas",
            )
            session.flush()
            self.assertEqual(session.query(ScanManifest).filter_by(scan_id="scan-1").count(), 2)

            with self.assertRaisesRegex(QuestionBankImportError, "Existing scan manifest"):
                import_selected_questions_to_question_bank(
                    session,
                    client_id="client-1",
                    scan_id="scan-1",
                    selected_at=selected_at + timedelta(minutes=1),
                    rows=[rows[0], rows[2]],
                    vertical="b2b_saas",
                )
        finally:
            session.close()

    def test_unsupported_phase12_frame_is_controlled_import_error(self):
        session = self.Session()
        try:
            rows = self._seed_import_fixture(session, count=1, brand_frame="not_a_frame")
            with self.assertRaisesRegex(QuestionBankImportError, "Unsupported Phase 12 brand_frame"):
                import_selected_questions_to_question_bank(
                    session,
                    client_id="client-1",
                    scan_id="scan-1",
                    selected_at=datetime.now(timezone.utc),
                    rows=rows,
                    vertical="b2b_saas",
                )
        finally:
            session.close()

    def _seed_import_fixture(
        self,
        session,
        *,
        count: int,
        brand_frame: str = "unbranded_category",
    ) -> list[tuple[QuestionCandidate, QuestionScore]]:
        session.add(User(id="user-1", email="founder@example.com"))
        session.add(Client(id="client-1", user_id="user-1", name="VectorCRM", url="https://vector.example"))
        rows: list[tuple[QuestionCandidate, QuestionScore]] = []
        scored_at = datetime.now(timezone.utc)
        for index in range(count):
            text = f"what should buyers evaluate for VectorCRM option {index}?"
            candidate = QuestionCandidate(
                id=f"candidate-{index}",
                client_id="client-1",
                text=text,
                text_hash=question_text_hash(text),
                journey_stage="J2",
                brand_frame=brand_frame,
                intent_class="informational",
                persona="VP Sales",
                locality="L0",
                realism_score=Decimal("8.000"),
                selected=True,
                generator_version="question_generation-test",
                realism_filter_version="realism_filter-test",
            )
            score = QuestionScore(
                question_id=candidate.id,
                scored_at=scored_at + timedelta(milliseconds=index),
                d1_buyer_plausibility=Decimal("8.000"),
                d2_commercial_proximity=Decimal("8.000"),
                d3_cognitive_answerability=Decimal("8.000"),
                d4_diagnostic_power=Decimal("8.000"),
                d5_statistical_identifiability=Decimal("8.000"),
                weighted_score=Decimal("8.000"),
                scorer_version="question_scorer-test",
            )
            session.add(candidate)
            session.add(score)
            rows.append((candidate, score))
        session.flush()
        return rows


if __name__ == "__main__":
    unittest.main()
