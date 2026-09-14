import unittest

from full_stack.gap_report import GapReportInput, build_gap_report
from full_stack.scan_metrics import ClientIdentity


class GapReportTests(unittest.TestCase):
    def test_gap_report_shows_appeared_missed_sources_and_ranked_fixes(self):
        identity = ClientIdentity(
            focal_name="PemSpa Skincare & Wellness",
            focal_aliases=("PemSpa Skincare & Wellness", "PemSpa"),
            competitors=("Bella Boutique Spa", "Glowbar Chestnut Hill"),
        )
        fieldnames = [
            "question",
            "group",
            "response_perplexity",
            "error_perplexity",
            "response_openai",
            "error_openai",
        ]
        rows = [
            {
                "question": "best chemical peel near Newton Centre, MA?",
                "group": "G4",
                "response_perplexity": (
                    "Bella Boutique Spa is commonly cited for peels. "
                    "[Yelp](https://www.yelp.com/biz/bella-boutique-spa?utm_source=ai)"
                ),
                "response_openai": (
                    "PemSpa Skincare & Wellness offers chemical peel options. "
                    "[PemSpa](https://pempsa.com/chemical-peel)"
                ),
            },
            {
                "question": "HydraFacial alternative near Newton Centre, MA?",
                "group": "G7",
                "response_perplexity": (
                    "Glowbar Chestnut Hill may appear for facial alternatives. "
                    "[Glowbar](https://glowbar.com/chestnut-hill)"
                ),
                "response_openai": "Bella Boutique Spa and Glowbar are visible options.",
            },
            {
                "question": "Client-authored question that also counts toward gaps?",
                "group": "MANUAL",
                "response_perplexity": "Bella Boutique Spa appears here.",
                "response_openai": "Glowbar Chestnut Hill appears here.",
            },
        ]

        report = build_gap_report(
            GapReportInput(
                rows=rows,
                fieldnames=fieldnames,
                identity=identity,
                client_url="https://pempsa.com",
                scan_id="scan-1",
                client_id="client-1",
                client_name="PemSpa",
            )
        )

        # The MANUAL row adds two more provider-question results, and PemSpa is
        # absent from both, so it lands wholly on the missed side.
        self.assertEqual(report["summary"]["total_provider_question_results"], 6)
        self.assertEqual(report["summary"]["appeared_count"], 1)
        self.assertEqual(report["summary"]["missed_count"], 5)
        self.assertTrue(any(not item["appeared"] for item in report["query_results"]))
        self.assertTrue(any(item["group"] == "MANUAL" for item in report["query_results"]))
        self.assertTrue(any(item["domain"] == "yelp.com" for item in report["source_opportunities"]))
        self.assertTrue(any(item["name"] == "Glowbar Chestnut Hill" for item in report["competitor_gaps"]))
        self.assertTrue(report["priority_fixes"])
        self.assertTrue(any("Close" in item["title"] or "proof" in item["title"].lower() for item in report["priority_fixes"]))


if __name__ == "__main__":
    unittest.main()
