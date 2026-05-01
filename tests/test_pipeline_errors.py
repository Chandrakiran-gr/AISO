import unittest
import csv
import tempfile
from pathlib import Path

from api.routes.pipeline import _estimate_api_calls, _extract_script_failure, _public_error


class PipelineErrorTests(unittest.TestCase):
    def test_extracts_collect_runtime_error_for_user(self):
        output = """
Traceback (most recent call last):
  File "/repo/full_stack/collect.py", line 805, in main
RuntimeError: 5 consecutive empty responses — likely an API configuration issue. Check your keys and quota.
"""

        message = _extract_script_failure("collect.py", 1, output)

        self.assertEqual(
            message,
            "5 consecutive empty responses — likely an API configuration issue. Check your keys and quota.",
        )

    def test_falls_back_to_exit_code_without_useful_output(self):
        self.assertEqual(
            _extract_script_failure("collect.py", 1, ""),
            "collect.py failed with exit code 1",
        )

    def test_public_error_hides_generic_collect_exit_code(self):
        self.assertEqual(
            _public_error("collect.py exited with code 1"),
            (
                "Scan collection failed. Check the selected provider API keys, quota, "
                "and rate limits, then run a new scan."
            ),
        )

    def test_estimates_api_calls_from_selected_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            bank = Path(tmp) / "query_template_bank.csv"
            with bank.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["question", "group"])
                writer.writeheader()
                for index in range(3):
                    writer.writerow({"question": f"G1 question {index}", "group": "G1"})
                for index in range(2):
                    writer.writerow({"question": f"G2 question {index}", "group": "G2"})

            estimate = _estimate_api_calls(
                bank,
                groups=["G1", "G2"],
                providers=["openai", "gemini"],
                pick_all=2,
            )

        self.assertEqual(estimate, (4, 2, 8))

    def test_estimates_api_calls_from_curated_bank_without_pick_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            bank = Path(tmp) / "query_template_bank.csv"
            with bank.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["question", "group"])
                writer.writeheader()
                for index in range(3):
                    writer.writerow({"question": f"G1 question {index}", "group": "G1"})
                for index in range(2):
                    writer.writerow({"question": f"G2 question {index}", "group": "G2"})

            estimate = _estimate_api_calls(
                bank,
                groups=["G1", "G2"],
                providers=["openai", "gemini"],
                pick_all=None,
            )

        self.assertEqual(estimate, (5, 2, 10))


if __name__ == "__main__":
    unittest.main()
