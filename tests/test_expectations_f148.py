r"""F-148 (总工单 v2 T4/N-2) 期望判定三件套回归钉。

独立文件的原因: expectations.py 的"双写收敛" (P2-3) 排在本任务之后由
Claude 做——新字段的测试放这里, 避免共享测试文件冲突面 (任务清单 §2 T4 警告)。

三件套契约:
  ① 行终止符语义 (防早判): 判定发生在采集窗超时后, 全文 (含未终止尾行)
     参与匹配——"未终止的值超时才判"; 命中仅落在未终止尾行时结果行标注
     `unterminated_hit: true` (值可能被截断, 消费方谨慎), 状态不变,
     既有清单零回归。
  ② ordered: true 按序命中 — texts 依次 find / patterns 依次 search(自
     上一 match.end()); 默认 False, 既有"任意位置命中"语义零改动。
  ③ record: 命名捕获组 — patterns[0] 全量匹配, 行级 records + 顶层
     records 平铺数组; 与 capture_group/min/max 互斥 (loader E + lint E12)。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import expectations  # noqa: E402
import expectations_lint  # noqa: E402


class UnterminatedHitTests(unittest.TestCase):
    """① 行终止符语义: 标注不翻状态"""

    def test_tail_only_hit_annotated(self):
        # 命中仅存在于未终止尾行 (有已终止前缀, 命中避开它) → 标注, 状态仍 pass
        ev = expectations.evaluate_expectations(
            "boot\nADC mv=3192", [{"id": "A", "patterns": [r"mv=(\d+)"],
                                   "capture_group": 1, "min": 3000, "max": 3400}])
        row = ev["results"][0]
        self.assertEqual(row["status"], "pass")
        self.assertTrue(row["unterminated_hit"])

    def test_no_terminated_line_not_annotated(self):
        # 全文无任何终止行: 无相对信号可归因 (半主机收尾常无换行) → 不标注
        ev = expectations.evaluate_expectations(
            "ADC mv=3192", [{"id": "A", "texts": ["mv=3192"]}])
        self.assertNotIn("unterminated_hit", ev["results"][0])

    def test_terminated_hit_not_annotated(self):
        ev = expectations.evaluate_expectations(
            "ADC mv=3192\n", [{"id": "A", "texts": ["mv=3192"]}])
        self.assertNotIn("unterminated_hit", ev["results"][0])

    def test_terminated_hit_with_junk_tail_not_annotated(self):
        # 命中在已终止行, 尾行只有无关内容 → 不标注
        ev = expectations.evaluate_expectations(
            "boot ok\nADC mv=3192\npartial", [{"id": "A", "texts": ["boot ok"]}])
        self.assertNotIn("unterminated_hit", ev["results"][0])

    def test_truncated_value_still_fails_range(self):
        # 防早判场景本体: 窗口关闭时值被截断 ("mv=319" 实为 3192 前缀)
        # → 判定如实体现在数值边界上, 不因早判误 PASS
        ev = expectations.evaluate_expectations(
            "ADC mv=319", [{"id": "A", "patterns": [r"mv=(\d+)"],
                            "capture_group": 1, "min": 3000, "max": 3400}])
        self.assertEqual(ev["results"][0]["status"], "fail")

    def test_annotation_never_flips_states(self):
        # 标注只加元数据, 不翻状态: xfail 条目在未终止行命中 → 仍按
        # XPASS 严格红处理 (不降级成 xfail, 也不因标注变绿)
        ev = expectations.evaluate_expectations(
            "feat ok", [{"id": "A", "texts": ["feat"], "xfail": True,
                         "xfail_reason": "wip"}])
        self.assertEqual(ev["results"][0]["status"], "xpass")
        self.assertNotIn("unterminated_hit", ev["results"][0])
        # 未终止行命中 + xfail: 命中不可信但状态语义不变 (xpass 红照红)
        ev2 = expectations.evaluate_expectations(
            "boot\nfeat", [{"id": "A", "texts": ["feat"], "xfail": True,
                            "xfail_reason": "wip"}])
        self.assertEqual(ev2["results"][0]["status"], "xpass")
        self.assertTrue(ev2["results"][0]["unterminated_hit"])
        self.assertEqual(ev2["verdict"], "fail")


class OrderedMatchTests(unittest.TestCase):
    """② ordered: true 按序命中; 默认 False 零回归"""

    def test_ordered_texts_in_order_pass(self):
        ev = expectations.evaluate_expectations(
            "init\nstart\nstart done",
            [{"id": "A", "texts": ["init", "start", "done"], "ordered": True}])
        self.assertEqual(ev["verdict"], "ok")

    def test_ordered_texts_out_of_order_fails(self):
        ev = expectations.evaluate_expectations(
            "start\ninit",
            [{"id": "A", "texts": ["init", "start"], "ordered": True}])
        self.assertEqual(ev["results"][0]["status"], "fail")
        self.assertIn("ordered", ev["results"][0]["detail"])

    def test_ordered_patterns_sequential_positions(self):
        # 第二个 pattern 必须命中在第一个 match 之后 ("abc" 仅在前 → 不可用)
        item = {"id": "A", "patterns": [r"STEP1", r"abc"], "ordered": True}
        self.assertEqual(
            expectations.evaluate_expectations("abc STEP1", [item])["verdict"],
            "fail")
        self.assertEqual(
            expectations.evaluate_expectations("abc STEP1 abc", [item])["verdict"],
            "ok")

    def test_no_ordered_key_zero_regression(self):
        # 默认 (无 ordered 键): 任意位置命中 — 既有语义逐字节不变
        item = {"id": "A", "patterns": [r"STEP1", r"abc"]}
        self.assertEqual(
            expectations.evaluate_expectations("abc STEP1 abc", [item])["verdict"],
            "ok")

    def test_ordered_with_capture_group_uses_first_match(self):
        item = {"id": "R", "patterns": [r"Hz=(\d+)"], "ordered": True,
                "capture_group": 1, "min": 2, "max": 99}
        self.assertEqual(
            expectations.evaluate_expectations("Hz=5 Hz=50", [item])["verdict"],
            "ok")   # 数值断言仍作用于 patterns[0] 首个 match (5)


class RecordCaptureTests(unittest.TestCase):
    """③ record 命名捕获组 → records 数组"""

    ITEM = {"id": "ADC", "patterns": [r"mv=(?P<mv>\d+)"],
            "record": ["mv"]}

    def test_records_per_row_and_top_level_flat(self):
        ev = expectations.evaluate_expectations(
            "mv=3192\nmv=3190\n", [dict(self.ITEM)])
        row = ev["results"][0]
        self.assertEqual(row["status"], "pass")
        self.assertEqual(row["records"], [{"mv": "3192"}, {"mv": "3190"}])
        self.assertEqual(ev["records"],
                         [{"id": "ADC", "mv": "3192"},
                          {"id": "ADC", "mv": "3190"}])

    def test_multiple_named_groups(self):
        item = {"id": "X", "patterns": [r"(?P<port>ADC\d+) ch(?P<ch>\d+)"],
                "record": ["port", "ch"]}
        ev = expectations.evaluate_expectations(
            "ADC1 ch3 ready", [item])
        self.assertEqual(ev["records"], [{"id": "X", "port": "ADC1", "ch": "3"}])

    def test_no_match_yields_empty_records(self):
        ev = expectations.evaluate_expectations("nothing here",
                                                [dict(self.ITEM)])
        self.assertEqual(ev["results"][0]["status"], "fail")
        self.assertEqual(ev["results"][0]["records"], [])
        self.assertEqual(ev["records"], [])

    def test_record_mutually_exclusive_with_capture_group(self):
        bad = {"id": "B", "patterns": [r"mv=(?P<mv>\d+)"], "record": ["mv"],
               "capture_group": 1, "min": 0}
        errors, _ = expectations_lint.lint_expectations([bad])
        self.assertTrue(any("E12" in e and "互斥" in e for e in errors))


class LoaderAndLintValidationTests(unittest.TestCase):
    """新字段的结构校验: loader 抛 ExpectationError, lint 报 E12/E13"""

    def _lint(self, item):
        return expectations_lint.lint_expectations([item])

    def test_record_requires_patterns(self):
        errors, _ = self._lint({"id": "A", "desc": "d", "texts": ["x"],
                                "record": ["mv"]})
        self.assertTrue(any("E12" in e for e in errors))

    def test_record_needs_non_empty_string_array(self):
        for bad in ([], [" "], "mv", [1]):
            errors, _ = self._lint({"id": "A", "desc": "d",
                                    "patterns": [r"mv=(?P<mv>\d+)"],
                                    "record": bad})
            self.assertTrue(any("E12" in e for e in errors), bad)

    def test_record_undefined_named_group(self):
        errors, _ = self._lint({"id": "A", "desc": "d",
                                "patterns": [r"mv=(?P<mv>\d+)"],
                                "record": ["voltage"]})
        self.assertTrue(any("E12" in e and "voltage" in e for e in errors))

    def test_ordered_must_be_bool(self):
        errors, _ = self._lint({"id": "A", "desc": "d", "texts": ["x"],
                                "ordered": "yes"})
        self.assertTrue(any("E13" in e for e in errors))

    def test_clean_record_and_ordered_item_passes_lint(self):
        item = {"id": "A", "desc": "d", "patterns": [r"mv=(?P<mv>\d+)"],
                "record": ["mv"], "ordered": True}
        errors, _ = self._lint(item)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
