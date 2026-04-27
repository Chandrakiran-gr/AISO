import unittest

from api.routes.pipeline import _extract_script_failure


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


if __name__ == "__main__":
    unittest.main()
