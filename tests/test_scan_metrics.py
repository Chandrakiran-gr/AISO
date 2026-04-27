import json
import tempfile
import unittest
from pathlib import Path

from full_stack.scan_metrics import (
    ClientIdentity,
    aggregate_scan_results,
    extract_scan_citations,
    load_client_identity,
)


class ScanMetricsTests(unittest.TestCase):
    def test_aggregates_provider_group_visibility(self):
        identity = ClientIdentity(
            focal_name="PemSpa Skincare & Wellness",
            focal_aliases=("PemSpa Skincare & Wellness", "PemSpa"),
            competitors=("Bella Boutique Spa", "Christine's Day Spa"),
        )
        fieldnames = [
            "question",
            "group",
            "response_openai",
            "error_openai",
            "response_claude",
            "error_claude",
        ]
        rows = [
            {
                "question": "best facials in Newton",
                "group": "G1",
                "response_openai": (
                    "Bella Boutique Spa is popular, while PemSpa is a strong "
                    "boutique option. Christine's Day Spa is another choice."
                ),
                "response_claude": "PemSpa Skincare & Wellness is often recommended.",
            },
            {
                "question": "facial spa near me",
                "group": "G1",
                "response_openai": (
                    "Bella Boutique Spa and Christine's Day Spa are local options."
                ),
                "response_claude": "",
            },
            {
                "question": "is PemSpa good",
                "group": "G2",
                "response_openai": "PemSpa is known for customized facials.",
                "response_claude": "Christine's Day Spa appears before PemSpa here.",
            },
        ]

        results = {
            (item.provider, item.group): item
            for item in aggregate_scan_results(rows, fieldnames, identity)
        }

        self.assertEqual(results[("openai", "G1")].total_questions, 2)
        self.assertEqual(results[("openai", "G1")].mention_count, 1)
        self.assertEqual(results[("openai", "G1")].visibility_score, 50.0)
        self.assertEqual(results[("openai", "G1")].avg_position, 2.0)
        self.assertEqual(
            results[("openai", "G1")].competitor_data,
            {"Bella Boutique Spa": 2, "Christine's Day Spa": 2},
        )
        self.assertEqual(results[("claude", "G2")].avg_position, 2.0)

    def test_loads_identity_from_client_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "client_profile.json").write_text(
                json.dumps(
                    {
                        "display_name": "PemSpa Skincare & Wellness",
                        "competitors": ["Bella Boutique Spa"],
                    }
                ),
                encoding="utf-8",
            )

            identity = load_client_identity(folder)

        self.assertEqual(identity.focal_name, "PemSpa Skincare & Wellness")
        self.assertIn("PemSpa", identity.focal_aliases)
        self.assertEqual(identity.competitors, ("Bella Boutique Spa",))

    def test_extracts_citations_and_dedupes_only_within_answer(self):
        fieldnames = [
            "question",
            "group",
            "response_perplexity",
            "error_perplexity",
        ]
        rows = [
            {
                "question": "best facials",
                "group": "G1",
                "response_perplexity": (
                    "PemSpa is mentioned by [Local Guide](https://Example.com/page/?utm_source=ai&b=2&a=1). "
                    "Duplicate link [Again](https://example.com/page/?a=1&b=2#frag) "
                    "and a bare URL https://source.example/review?utm_campaign=test."
                ),
            },
            {
                "question": "is PemSpa legit",
                "group": "G5",
                "response_perplexity": (
                    "The same source can repeat across questions: "
                    "[Local Guide](https://example.com/page/?a=1&b=2)."
                ),
            },
        ]

        citations = extract_scan_citations(rows, fieldnames)

        self.assertEqual(len(citations), 3)
        self.assertEqual(citations[0].citation_url, "https://example.com/page?a=1&b=2")
        self.assertEqual(citations[0].citation_title, "Local Guide")
        self.assertEqual(citations[0].source_domain, "example.com")
        self.assertEqual(citations[0].source_rank, 1)
        self.assertEqual(citations[1].citation_url, "https://source.example/review")
        self.assertEqual(citations[2].question, "is PemSpa legit")


if __name__ == "__main__":
    unittest.main()
