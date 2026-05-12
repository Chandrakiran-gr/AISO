import unittest
from collections import OrderedDict

from full_stack.collect import _interactive_group_picker


class CollectPickerManualTests(unittest.TestCase):
    def test_pick_all_cap_does_not_drop_manual_questions(self):
        grouped = OrderedDict(
            [
                (
                    "G1",
                    [
                        {"question": f"G1 question {index}", "group": "G1", "group_rank": str(index)}
                        for index in range(1, 7)
                    ],
                ),
                (
                    "MANUAL",
                    [
                        {
                            "question": f"Manual question {index}",
                            "group": "MANUAL",
                            "group_label": "Custom Questions",
                            "group_rank": str(index),
                        }
                        for index in range(1, 10)
                    ],
                ),
            ]
        )

        selected = _interactive_group_picker(grouped, pick_all=3)

        self.assertEqual(len([row for row in selected if row["group"] == "G1"]), 3)
        self.assertEqual(len([row for row in selected if row["group"] == "MANUAL"]), 9)


if __name__ == "__main__":
    unittest.main()
