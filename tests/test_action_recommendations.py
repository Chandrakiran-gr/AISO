import json
import unittest

from full_stack.action_recommendations import build_action_recommendations
from full_stack.scan_metrics import AggregatedScanResult, ExtractedCitation


def result(
    provider: str,
    group: str,
    total: int,
    mentions: int,
    competitors: dict[str, int] | None = None,
) -> AggregatedScanResult:
    return AggregatedScanResult(
        provider=provider,
        group=group,
        total_questions=total,
        mention_count=mentions,
        avg_position=None,
        visibility_score=round((mentions / total) * 100, 2) if total else 0,
        competitor_data=competitors or {},
    )


def citation(provider: str, group: str, domain: str) -> ExtractedCitation:
    return ExtractedCitation(
        provider=provider,
        group=group,
        question="Which business should I choose?",
        answer_excerpt="AISO Demo is cited as a useful source.",
        citation_url=f"https://{domain}/proof",
        citation_title="Proof",
        source_domain=domain,
        source_rank=1,
        metadata={},
    )


def classified_citation(
    provider: str,
    group: str,
    domain: str,
    *,
    source_type: str,
    owner_type: str,
    action_role: str,
) -> ExtractedCitation:
    return ExtractedCitation(
        provider=provider,
        group=group,
        question=f"How should I compare source proof for {domain}?",
        answer_excerpt=f"{domain} was cited as evidence.",
        citation_url=f"https://{domain}/proof",
        citation_title="Proof",
        source_domain=domain,
        source_rank=1,
        metadata={},
        canonical_url=f"https://{domain}/proof",
        source_type=source_type,
        owner_type=owner_type,
        action_role=action_role,
        actionability_score=8.2,
        confidence_score=8.0,
    )


class ActionRecommendationTests(unittest.TestCase):
    def action_keys(self, actions: list[dict]) -> set[str]:
        return {str(action["action_key"]) for action in actions}

    def test_low_overall_score_creates_entity_action(self):
        actions = build_action_recommendations([
            result("openai", "G1", 10, 0),
        ])

        self.assertIn("overall:entity-foundation", self.action_keys(actions))
        entity = next(action for action in actions if action["action_key"] == "overall:entity-foundation")
        self.assertEqual(entity["priority"], "high")
        self.assertEqual(json.loads(entity["evidence_json"])["overall_score"], 0.0)

    def test_weak_group_creates_group_specific_content_action(self):
        actions = build_action_recommendations([
            result("openai", "G5", 12, 2),
            result("gemini", "G2", 12, 10),
        ])

        self.assertIn("group:G5:answer-content", self.action_keys(actions))
        weak_group = next(action for action in actions if action["action_key"] == "group:G5:answer-content")
        evidence = json.loads(weak_group["evidence_json"])
        self.assertEqual(evidence["group"], "G5")
        self.assertEqual(evidence["score"], 16.67)

    def test_provider_gap_creates_provider_specific_action(self):
        actions = build_action_recommendations([
            result("openai", "G2", 10, 9),
            result("gemini", "G2", 10, 0),
        ])

        self.assertIn("provider:gemini:visibility-gap", self.action_keys(actions))
        provider_action = next(
            action for action in actions if action["action_key"] == "provider:gemini:visibility-gap"
        )
        self.assertEqual(json.loads(provider_action["evidence_json"])["provider"], "gemini")

    def test_competitor_pressure_creates_competitor_action(self):
        actions = build_action_recommendations([
            result("perplexity", "G3", 10, 2, {"Rival Spa": 8}),
        ])

        self.assertIn("competitor:rival spa:close-gap", self.action_keys(actions))
        competitor = next(
            action for action in actions if action["action_key"] == "competitor:rival spa:close-gap"
        )
        self.assertEqual(json.loads(competitor["evidence_json"])["competitor"], "Rival Spa")

    def test_missing_citations_creates_proof_action(self):
        actions = build_action_recommendations([
            result("openai", "G2", 10, 6),
            result("perplexity", "G2", 10, 6),
        ])

        self.assertIn("proof:citeable-sources", self.action_keys(actions))

    def test_listing_sources_create_source_action(self):
        actions = build_action_recommendations(
            [result("perplexity", "G4", 10, 6)],
            citations=[
                classified_citation(
                    "perplexity",
                    "G4",
                    "booksy.com",
                    source_type="marketplace_or_booking",
                    owner_type="third_party",
                    action_role="listing_or_profile_target",
                ),
                classified_citation(
                    "openai",
                    "G4",
                    "fresha.com",
                    source_type="marketplace_or_booking",
                    owner_type="third_party",
                    action_role="listing_or_profile_target",
                ),
            ],
        )

        self.assertIn("source:listing_or_profile_target:marketplace_or_booking:improve", self.action_keys(actions))

    def test_authority_sources_create_content_gap_action(self):
        actions = build_action_recommendations(
            [result("perplexity", "G6", 10, 6)],
            citations=[
                classified_citation(
                    "perplexity",
                    "G6",
                    "aad.org",
                    source_type="authority_reference",
                    owner_type="third_party",
                    action_role="content_gap_signal",
                )
            ],
        )

        self.assertIn("source:authority_reference:content-gap", self.action_keys(actions))

    def test_competitor_owned_sources_create_competitive_evidence_action(self):
        actions = build_action_recommendations(
            [result("perplexity", "G7", 10, 6)],
            citations=[
                classified_citation(
                    "perplexity",
                    "G7",
                    "glowbar.com",
                    source_type="competitor_site",
                    owner_type="competitor_owned",
                    action_role="competitive_evidence",
                )
            ],
        )

        self.assertIn("source:competitor_site:competitive-evidence", self.action_keys(actions))

    def test_strong_scan_creates_maintenance_action_when_evidence_is_healthy(self):
        actions = build_action_recommendations(
            [
                result("openai", "G2", 10, 8),
                result("perplexity", "G5", 10, 8),
            ],
            citations=[
                citation("openai", "G2", "example.com"),
                citation("perplexity", "G5", "reviews.example"),
                citation("perplexity", "G5", "local.example"),
            ],
        )

        self.assertIn("maintenance:scan-review", self.action_keys(actions))

    def test_reranking_is_stable_deduped_and_limited(self):
        actions = build_action_recommendations([
            result("openai", "G1", 10, 0),
            result("openai", "G2", 10, 0),
            result("openai", "G3", 10, 0),
            result("openai", "G4", 10, 0),
            result("openai", "G5", 10, 0),
            result("gemini", "G1", 10, 0),
        ])

        self.assertLessEqual(len(actions), 5)
        self.assertEqual(len(actions), len(self.action_keys(actions)))
        self.assertEqual(
            [action["sort_order"] for action in actions],
            list(range(1, len(actions) + 1)),
        )


if __name__ == "__main__":
    unittest.main()
