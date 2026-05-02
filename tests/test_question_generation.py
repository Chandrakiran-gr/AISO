import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.question_generation import (
    DEFAULT_GROUP_TARGETS,
    QuestionCandidate,
    audit_question_bank_rows,
    profile_to_question_rows,
    validate_question,
)


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
    "buyer_contexts": [
        {
            "label": "Sensitive-skin buyers",
            "audience_type": "primary",
            "problem": "redness, clogged pores, and irritation",
            "desired_outcome": "get calmer glowing skin before an event",
            "trigger_event": "upcoming wedding or photoshoot",
            "constraints": "sensitive skin and low downtime",
            "decision_criteria": "proof, reviews, safe ingredients, and pricing clarity",
            "priority": "high",
            "source": "manual",
            "confidence": 0.95,
        }
    ],
    "scan_objective": {
        "objective": "improve_high_intent_visibility",
        "label": "Improve high-intent buyer visibility",
        "custom": "",
    },
    "differentiators": [],
    "guardrails": [],
}


class QuestionGenerationTests(unittest.TestCase):
    def test_context_questions_are_conversational_and_grouped(self):
        rows = profile_to_question_rows(PROFILE)

        self.assertEqual(len(rows), sum(DEFAULT_GROUP_TARGETS.values()))
        self.assertEqual({row["group"] for row in rows}, {"G1", "G2", "G3", "G4", "G5", "G6", "G7"})
        self.assertTrue(all(row["question"].endswith("?") for row in rows))
        self.assertTrue(any(row["intent_subtype"] == "near_me" for row in rows))
        self.assertFalse(any("near me" in row["question"].casefold() for row in rows))
        self.assertTrue(any(row["query_mode"] == "keyword" for row in rows))
        self.assertTrue(any("Pempsa chemical peel?" == row["question"] for row in rows))
        self.assertTrue(all(row["rank_reason"].startswith("High value:") for row in rows))
        self.assertTrue(all("objective_alignment_score" in row for row in rows))
        self.assertTrue(all("buyer_context_score" in row for row in rows))

    def test_group_target_env_override_controls_selection(self):
        with patch.dict("os.environ", {"AISO_QUESTION_GROUP_TARGETS": "G1:2,G2:3,G3:4"}, clear=False):
            rows = profile_to_question_rows(PROFILE, selected_groups=["G1", "G2", "G3"])

        counts = {group: sum(1 for row in rows if row["group"] == group) for group in {"G1", "G2", "G3"}}
        self.assertEqual(counts, {"G1": 2, "G2": 3, "G3": 4})
        self.assertEqual(len(rows), 9)

    def test_transactional_questions_include_price_and_booking_intent(self):
        rows = profile_to_question_rows(PROFILE)
        g4 = [row for row in rows if row["group"] == "G4"]

        self.assertTrue(any(row["intent_subtype"] == "price" for row in g4))
        self.assertTrue(any("book" in row["question"].lower() for row in g4))

    def test_buyer_contexts_create_cross_industry_problem_outcome_and_decision_questions(self):
        examples = [
            (
                "SaaSCo",
                "B2B compliance software",
                "reduce SOC 2 audit prep time",
                "launch security questionnaire automation",
            ),
            (
                "Oak Home Services",
                "emergency plumbing service",
                "fix a burst pipe without water damage",
                "find a same-day plumber with transparent pricing",
            ),
        ]
        for business_name, category, problem, outcome in examples:
            profile = {
                "business": {"name": business_name},
                "categories": [{"name": category, "type": "category"}],
                "offerings": [{"name": category, "type": "offering", "bookable": True}],
                "offering_groups": [],
                "product_brands": [],
                "competitors": [],
                "locations": {
                    "physical_locations": [],
                    "service_areas": [{"name": "United States", "type": "service_area"}],
                    "visibility_markets": [],
                    "excluded_locations": [],
                },
                "goals": [],
                "personas": [],
                "buyer_contexts": [
                    {
                        "label": "Urgent buyers",
                        "problem": problem,
                        "desired_outcome": outcome,
                        "constraints": "limited time and low risk tolerance",
                        "decision_criteria": "speed, proof, pricing, and support",
                        "priority": "high",
                        "source": "manual",
                        "confidence": 0.9,
                    }
                ],
                "differentiators": [],
                "guardrails": [],
            }
            rows = profile_to_question_rows(profile, selected_groups=["G6"], limit_per_group=80)
            questions = "\n".join(row["question"].lower() for row in rows)

            self.assertIn(problem.lower(), questions)
            self.assertIn(outcome.lower(), questions)
            self.assertTrue(any(float(row["buyer_context_score"]) > 0 for row in rows))

    def test_g7_without_competitors_keeps_reduced_method_coverage_only(self):
        no_competitor_profile = {**PROFILE, "competitors": []}

        rows = profile_to_question_rows(no_competitor_profile, selected_groups=["G7"], limit_per_group=80)
        questions = "\n".join(row["question"] for row in rows).casefold()

        self.assertTrue(rows)
        self.assertFalse(any(row["intent_subtype"] == "head_to_head" for row in rows))
        self.assertTrue(any(row["intent_subtype"] in {"method_comparison", "adjacency"} for row in rows))
        self.assertNotIn("another local business", questions)
        self.assertNotIn("leading competitor", questions)

    def test_aftercare_and_support_layer_is_not_spa_specific(self):
        saas_profile = {
            "business": {"name": "SaaSCo"},
            "categories": [{"name": "B2B compliance software", "type": "category"}],
            "offerings": [{"name": "security questionnaire automation", "type": "offering", "bookable": True}],
            "offering_groups": [],
            "product_brands": [],
            "competitors": [],
            "locations": {
                "physical_locations": [],
                "service_areas": [{"name": "United States", "type": "service_area"}],
                "visibility_markets": [],
                "excluded_locations": [],
            },
            "goals": [],
            "personas": [],
            "buyer_contexts": [],
            "scan_objective": {
                "objective": "improve_trust_and_citation_proof",
                "label": "Improve trust, reviews, and citation proof",
            },
            "differentiators": [],
            "guardrails": [],
        }

        rows = profile_to_question_rows(saas_profile, selected_groups=["G5"], limit_per_group=80)
        questions = "\n".join(row["question"].lower() for row in rows)

        self.assertIn("onboarding", questions)
        self.assertIn("support", questions)
        self.assertTrue(any(row["intent_subtype"] == "aftercare" for row in rows))

    def test_market_intent_bank_rejects_pempsa_noise_and_adds_missing_layers(self):
        noisy_profile = {
            **PROFILE,
            "offerings": [
                *PROFILE["offerings"],
                {
                    "name": "PemSpa signature facial is perfect for refreshing and rejuvenating skin affected by nature’s elements, everyday pollutants, or acne.",
                    "type": "offering",
                    "bookable": True,
                },
                {"name": "ADDITIONAL Facial ADD-ONS:", "type": "offering", "bookable": True},
                {"name": "Hydro Boost Facial", "type": "offering", "bookable": True},
            ],
            "goals": [{"name": "Choose the best provider", "type": "goal"}],
            "personas": [
                {
                    "name": "✨ Ideal for sensitive skin or anyone wanting hydrated, radiant results without harsh abrasion",
                    "type": "persona",
                }
            ],
            "locations": {
                **PROFILE["locations"],
                "physical_locations": [
                    {"name": "634 Commonwealth Avenue, Suite 209, Newton, MA 02459", "type": "physical_location"}
                ],
            },
        }

        rows = profile_to_question_rows(noisy_profile)
        questions = [row["question"] for row in rows]
        question_text = "\n".join(questions).lower()
        subtypes = {row["intent_subtype"] for row in rows}

        self.assertNotIn("another local business", question_text)
        self.assertNotIn("choose the best provider", question_text)
        self.assertNotIn("improve visibility for relevant buyer searches", question_text)
        self.assertNotIn("another approach", question_text)
        self.assertNotIn("additional facial add-ons", question_text)
        self.assertNotIn("634 commonwealth", question_text)
        self.assertNotIn("in near me", question_text)
        self.assertNotIn("near me", question_text)
        self.assertFalse(any("✨" in question for question in questions))
        self.assertIn("concern", subtypes)
        self.assertIn("method_comparison", subtypes)
        self.assertIn("adjacency", subtypes)
        self.assertTrue(any("HydraFacial" in question for question in questions))
        self.assertTrue(any("near Brookline, MA" in question for question in questions))
        self.assertTrue(any("Back Bay Boston, MA" in question or "Cambridge, MA" in question for question in questions))

    def test_internal_scan_objective_never_becomes_question_text(self):
        profile = {
            **PROFILE,
            "goals": [{"name": "Improve visibility for relevant buyer searches", "type": "goal"}],
            "buyer_contexts": [
                {
                    "label": "Primary buyers",
                    "problem": "Improve visibility for relevant buyer searches",
                    "desired_outcome": "choose a trusted facial spa",
                    "decision_criteria": "reviews and proof",
                }
            ],
        }

        rows = profile_to_question_rows(profile)
        questions = "\n".join(row["question"] for row in rows).casefold()

        self.assertNotIn("improve visibility for relevant buyer searches", questions)

    def test_question_bank_qc_report_is_written_and_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "question_ranking_report.json"
            rows = profile_to_question_rows(PROFILE, report_path=report_path)

            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text())

        self.assertTrue(report["quality_control"]["passed"])
        self.assertEqual(report["quality_control"]["coverage"]["total_questions"], len(rows))
        self.assertIn("near_me", report["quality_control"]["coverage"]["intent_subtypes"])

    def test_question_bank_qc_flags_rows_that_should_never_run(self):
        qc = audit_question_bank_rows(
            [
                {
                    "question": "Which is better for Choose the best provider: Pempsa or another local business?",
                    "group": "G7",
                    "intent_subtype": "head_to_head",
                    "query_mode": "conversational",
                    "priority": "high",
                },
                {
                    "question": "how much does chemical peel cost in near me?",
                    "group": "G4",
                    "intent_subtype": "price",
                    "query_mode": "keyword",
                    "priority": "high",
                },
                {
                    "question": "should I choose classic facial or another approach?",
                    "group": "G7",
                    "intent_subtype": "method_comparison",
                    "query_mode": "conversational",
                    "priority": "high",
                },
            ]
        )
        messages = " ".join(issue["message"] for issue in qc["issues"])

        self.assertFalse(qc["passed"])
        self.assertIn("unresolved competitor placeholder", messages)
        self.assertIn("unresolved goal placeholder", messages)
        self.assertIn("malformed near-me phrasing", messages)
        self.assertIn("vague comparison phrasing", messages)

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
