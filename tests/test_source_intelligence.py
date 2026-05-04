import unittest

from full_stack.source_intelligence import (
    canonicalize_url,
    classify_source,
    provider_result_to_evidence_records,
    score_source,
)
from webish.providers.base import ProviderCitation, ProviderResult, ProviderSearchResult


class SourceIntelligenceTests(unittest.TestCase):
    def test_canonicalize_url_strips_tracking_and_www(self):
        self.assertEqual(
            canonicalize_url("https://www.Example.com/path/?utm_source=x&b=2&a=1#frag"),
            "https://example.com/path?a=1&b=2",
        )

    def test_classifies_actionable_marketplace(self):
        classification = classify_source(
            "https://fresha.com/a/pemspa-newton",
            client_domain="pempsa.com",
            competitors=("Bella Boutique Spa",),
        )

        self.assertEqual(classification.source_type, "marketplace_or_booking")
        self.assertEqual(classification.action_role, "listing_or_profile_target")
        self.assertGreaterEqual(classification.actionability_score, 8)

    def test_classifies_competitor_owned_as_evidence_not_target(self):
        classification = classify_source(
            "https://glowbar.com/chestnut-hill",
            title="Glowbar Chestnut Hill",
            client_domain="pempsa.com",
            competitors=("Glowbar Chestnut Hill",),
        )

        self.assertEqual(classification.owner_type, "competitor_owned")
        self.assertEqual(classification.action_role, "competitive_evidence")

    def test_authority_source_becomes_content_gap(self):
        classification = classify_source(
            "https://www.aad.org/public/cosmetic/safety/microneedling",
            client_domain="pempsa.com",
        )

        self.assertEqual(classification.source_type, "authority_reference")
        self.assertEqual(classification.action_role, "content_gap_signal")

    def test_search_result_pages_are_noise_not_listing_targets(self):
        classification = classify_source(
            "https://www.google.com/search?q=best+facial+newton",
            client_domain="pempsa.com",
        )

        self.assertEqual(classification.source_type, "low_value_or_noise")
        self.assertEqual(classification.action_role, "ignore")

    def test_provider_result_exports_native_and_fallback_evidence(self):
        result = ProviderResult(
            response="PemSpa appears in [Yelp](https://www.yelp.com/biz/pemspa?utm_source=x).",
            provider="perplexity",
            model="sonar",
            web_search_used=True,
            citations=[
                ProviderCitation(
                    url="https://www.yelp.com/biz/pemspa?utm_source=x",
                    title="PemSpa on Yelp",
                    source_rank=1,
                )
            ],
            search_results=[
                ProviderSearchResult(
                    url="https://booksy.com/en-us/pemspa",
                    title="PemSpa booking",
                    snippet="Book online.",
                    result_rank=1,
                )
            ],
        )

        records = provider_result_to_evidence_records(
            result=result,
            provider_name="perplexity",
            question="best facial Newton",
            group="G1",
            scan_id="scan-1",
            client_id="client-1",
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["source"]["canonical_url"], "https://yelp.com/biz/pemspa")
        self.assertEqual(records[0]["web_search_used"], True)
        self.assertEqual(records[1]["source"]["origin"], "native_search_result")

    def test_scores_repeated_high_intent_source_higher(self):
        listing = classify_source("https://yelp.com/biz/pemspa")
        low_value = classify_source("https://google.com/search?q=pemspa")

        listing_score = score_source(
            citation_count=9,
            unique_question_count=7,
            provider_count=3,
            groups=("G4", "G6"),
            avg_source_rank=1.5,
            classification=listing,
            missed_query_count=7,
        )
        low_value_score = score_source(
            citation_count=1,
            unique_question_count=1,
            provider_count=1,
            groups=("G2",),
            avg_source_rank=8,
            classification=low_value,
        )

        self.assertGreater(listing_score.opportunity_score, low_value_score.opportunity_score)


if __name__ == "__main__":
    unittest.main()
