"""F-235: sequence 正断言 —— 抽出序号必须严格递增。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import expectations  # noqa: E402
import expectations_lint  # noqa: E402


def _item(**kw):
    base = {"id": "TICK-01", "desc": "tick 严格递增",
            "sequence": {"pattern": r"TICK (\d+)", "strict": True, "min_count": 3}}
    base.update(kw)
    return base


class SequenceEvalTests(unittest.TestCase):
    def test_strictly_increasing_passes(self):
        out = "TICK 0\nTICK 1\nTICK 2\n"
        res = expectations.evaluate_expectations(out, [_item()])
        self.assertEqual(res["results"][0]["status"], "pass")

    def test_regression_fails(self):
        out = "TICK 0\nTICK 1\nTICK 7\nTICK 3\n"
        res = expectations.evaluate_expectations(out, [_item()])
        self.assertEqual(res["results"][0]["status"], "fail")
        self.assertIn("单调", res["results"][0]["detail"])

    def test_duplicate_fails(self):
        out = "TICK 0\nTICK 1\nTICK 1\n"
        res = expectations.evaluate_expectations(out, [_item()])
        self.assertEqual(res["results"][0]["status"], "fail")

    def test_too_few_samples_fails(self):
        out = "TICK 0\nTICK 1\n"
        res = expectations.evaluate_expectations(out, [_item()])
        self.assertEqual(res["results"][0]["status"], "fail")
        self.assertIn("min_count", res["results"][0]["detail"])

    def test_forbidden_still_wins(self):
        out = "TICK 0\nTICK 1\nTICK 2\nHARDFAULT\n"
        res = expectations.evaluate_expectations(
            out, [_item(forbidden_texts=["HARDFAULT"])])
        self.assertEqual(res["results"][0]["status"], "fail")
        self.assertIn("forbidden", res["results"][0]["detail"])

    def test_non_strict_allows_regression(self):
        # strict=false 只查样本数, 不查单调 (键语义见 brief Interfaces)
        out = "TICK 0\nTICK 7\nTICK 3\n"
        res = expectations.evaluate_expectations(
            out, [_item(sequence={"pattern": r"TICK (\d+)", "strict": False,
                                  "min_count": 3})])
        self.assertEqual(res["results"][0]["status"], "pass")


class SequenceLintTests(unittest.TestCase):
    def test_three_way_exclusive(self):
        errs = expectations.item_rule_errors(
            {"id": "X", "desc": "d", "texts": ["a"],
             "sequence": {"pattern": r"T (\d+)"}})
        self.assertTrue(any(e[0] == "E4" for e in errs))

    def test_sequence_alone_is_legal(self):
        errs = expectations.item_rule_errors(_item())
        self.assertEqual(errs, [])

    def test_bad_pattern_rejected(self):
        errs = expectations.item_rule_errors(
            _item(sequence={"pattern": "T (", "min_count": 3}))
        self.assertTrue(any(e[0] == "E15" for e in errs))

    def test_bad_min_count_rejected(self):
        errs = expectations.item_rule_errors(
            _item(sequence={"pattern": r"T (\d+)", "min_count": 1}))
        self.assertTrue(any(e[0] == "E15" for e in errs))

    def test_non_dict_sequence_rejected(self):
        errs = expectations.item_rule_errors(_item(sequence="T (\\d+)"))
        self.assertTrue(any(e[0] == "E15" for e in errs))

    def test_bad_strict_rejected(self):
        errs = expectations.item_rule_errors(
            _item(sequence={"pattern": r"T (\d+)", "strict": "yes"}))
        self.assertTrue(any(e[0] == "E15" for e in errs))

    def test_sequence_with_capture_group_rejected(self):
        errs = expectations.item_rule_errors(_item(capture_group=1))
        self.assertTrue(any(e[0] == "E15" for e in errs))

    def test_sequence_with_record_rejected(self):
        errs = expectations.item_rule_errors(_item(record=["t"]))
        self.assertTrue(any(e[0] == "E15" for e in errs))

    def test_sequence_with_min_max_rejected(self):
        for kw in ({"min": 0}, {"max": 10}):
            errs = expectations.item_rule_errors(_item(**kw))
            self.assertTrue(any(e[0] == "E15" for e in errs), kw)

    def test_sequence_with_forbidden_fields_legal(self):
        # R3: sequence 与负断言并存合法 (check_forbidden_fields 不涉 sequence)
        item = _item(forbidden_texts=["HARDFAULT"],
                     forbidden_patterns=[r"\[E\] "])
        self.assertEqual(expectations.item_rule_errors(item), [])
        self.assertEqual(expectations.check_forbidden_fields(item), [])

    def test_lint_surfaces_e15(self):
        errors, _ = expectations_lint.lint_expectations(
            [_item(sequence={"pattern": "T ("})])
        self.assertTrue(any(e.startswith("E15") for e in errors))


if __name__ == "__main__":
    unittest.main()
