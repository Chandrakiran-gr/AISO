import unittest

from api.question_generation import QuestionCandidate, profile_to_question_rows, validate_question


PROFILE = {
    "business": {"name": "Pempsa"},
    "categories": [{"name": "boutique skincare spa", "type": "category"}],
    "offering_groups": [{"name": "Signature Facials", "type": "offering_group", "bookable": False}],
    "offerings": [
        {"name": "Chemical Peel", "type": "offering", "bookable": True},
        {"name": "Deluxe Dermaplane Facial", "type": "offering", "bookable": True},
    ],
    "product_brands": [{"name": "Face Reality", "type": "product_brand"}],
    "competitors": [{"name": "Bella Boutique Spa", "type": "competitor_business"}],
    "locations": {
        "physical_locations": [{"name": "Newton Centre, MA", "type": "physical_location"}],
        "service_areas": [{"name": "Brookline", "type": "service_area"}],
        "visibility_markets": [{"name": "Greater Boston", "type": "visibility_market", "usage": "visibility_only"}],
        "excluded_locations": [],
    },
    "goals": [{"name": "improve acne-prone skin", "type": "goal"}],
    "personas": [{"name": "first-time facial clients", "type": "persona"}],
    "differentiators": [],
    "guardrails": [],
}


class QuestionGenerationTests(unittest.TestCase):
    def test_context_questions_are_conversational_and_grouped(self):
        rows = profile_to_question_rows(PROFILE, limit_per_group=8)

        self.assertGreaterEqual(len(rows), 20)
        self.assertEqual({row["group"] for row in rows}, {"G1", "G2", "G3", "G4", "G5", "G6", "G7"})
        self.assertTrue(all(row["question"].endswith("?") for row in rows))
        self.assertTrue(any("Does Pempsa offer Chemical Peel?" == row["question"] for row in rows))

    def test_validator_rejects_service_vs_business_comparisons(self):
        ok, reason = validate_question(
            QuestionCandidate(
                "Chemical Peel vs Bella Boutique Spa: which is better?",
                "G7",
                {"group": "G7", "left_type": "offering", "right_type": "business"},
            )
        )

        self.assertFalse(ok)
        self.assertEqual(reason, "reject offering-vs-business comparison")

    def test_validator_rejects_product_brand_vs_service_comparisons(self):
        ok, _ = validate_question(
            QuestionCandidate(
                "Face Reality vs Chemical Peel for acne",
                "G7",
                {"group": "G7", "left_type": "product_brand", "right_type": "offering"},
            )
        )

        self.assertFalse(ok)

    def test_validator_allows_product_brand_when_phrase_is_uses_or_carries(self):
        ok, _ = validate_question(
            QuestionCandidate(
                "Does Pempsa use or carry Face Reality?",
                "G2",
                {"group": "G2", "left_type": "business", "right_type": "product_brand"},
            )
        )

        self.assertTrue(ok)

    def test_validator_rejects_urgent_booking_for_visibility_only_regions(self):
        ok, reason = validate_question(
            QuestionCandidate(
                "Where can I book Chemical Peel in Greater Boston?",
                "G4",
                {"group": "G4", "location_usage": "visibility_market", "left_type": "offering"},
            )
        )

        self.assertFalse(ok)
        self.assertEqual(reason, "reject urgent booking prompt for visibility-only market")

    def test_validator_rejects_unconfirmed_landmarks(self):
        ok, reason = validate_question(
            QuestionCandidate(
                "Who offers Chemical Peel near Fenway Park?",
                "G1",
                {"group": "G1", "location_usage": "landmark", "location_confirmed": False},
            )
        )

        self.assertFalse(ok)
        self.assertEqual(reason, "reject unconfirmed landmark")

    def test_generation_dedupes_near_identical_questions(self):
        noisy_profile = dict(PROFILE)
        noisy_profile["offerings"] = [
            {"name": "Chemical Peel", "type": "offering", "bookable": True},
            {"name": "Chemical Peel", "type": "offering", "bookable": True},
        ]

        rows = profile_to_question_rows(noisy_profile, limit_per_group=12)
        questions = [row["question"] for row in rows]

        self.assertEqual(len(questions), len(set(questions)))


if __name__ == "__main__":
    unittest.main()
