"""C 项补测 (2026-08-30 代管 R2): 零覆盖模块的纯函数/mock 测试.

覆盖对象 (此前无任何测试): phase_minus_one (预检四查+裁定)、rm_lookup
(参考手册检索)、svd_to_json (SVD 解析基元)。
全部纯逻辑或临时文件; 唯一的真实数据读取是 data/stm32f103-ref.json 冒烟
(只读, 不触硬件)。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import phase_minus_one  # noqa: E402
import rm_lookup  # noqa: E402
import svd_to_json  # noqa: E402

MIN_REF = {
    "peripherals": {
        "I2C1": {
            "registers": {
                "CR1": {"bits": {"1": {"name": "SMBALERT", "desc": "SMBus alert"},
                                 "PE": {"name": "PE", "desc": "enable"}}},
            },
            "recipes": [{"title": "init i2c", "code": "I2C1->CR1 |= PE;"}],
        },
        "USART1": {"registers": {"SR": {"bits": {}}}, "recipes": []},
    },
    "_relationships": {"CAN": {"pins": ["PA11", "PA12"]}},
}


class PhaseMinusOneTests(unittest.TestCase):
    def test_chip_support_three_tiers(self):
        self.assertEqual(
            phase_minus_one.check_chip_support("I2C1", MIN_REF)["status"], "OK")
        self.assertIn("FULL",
                      phase_minus_one.check_chip_support("I2C1", MIN_REF)["detail"])
        self.assertIn("PARTIAL",
                      phase_minus_one.check_chip_support("CAN", MIN_REF)["detail"])
        self.assertEqual(
            phase_minus_one.check_chip_support("USB", MIN_REF)["status"],
            "UNKNOWN")

    def test_pin_conflict_share_and_none(self):
        conflict = phase_minus_one.check_pin_conflicts(["pc13"], "USART1", MIN_REF)
        self.assertEqual(conflict["status"], "CONFLICT")
        self.assertIn("used by", conflict["detail"])
        share = phase_minus_one.check_pin_conflicts(["PC13"], "GPIO Output", MIN_REF)
        self.assertEqual(share["status"], "OK")
        none = phase_minus_one.check_pin_conflicts(["PA5"], "USART1", MIN_REF)
        self.assertEqual(none["status"], "OK")
        empty = phase_minus_one.check_pin_conflicts([], "USART1", MIN_REF)
        self.assertEqual(empty["detail"], "No pins specified")

    def test_known_issues_prefix_match_with_workaround(self):
        issues = {"I2C": {"busy_flag": "I2C2 may stick BUSY",
                          "workaround": "fall back to SW I2C"}}
        out = phase_minus_one.check_known_issues("I2C2", issues)
        self.assertEqual(out["status"], "WARN")
        self.assertEqual(out["workaround"], "fall back to SW I2C")
        self.assertIn("busy_flag", out["detail"])

    def test_known_issues_empty_db(self):
        self.assertEqual(
            phase_minus_one.check_known_issues("I2C2", {})["status"], "OK")
        self.assertEqual(
            phase_minus_one.check_known_issues("USART1", {"I2C": {"x": "y"}})["status"],
            "OK")

    def test_compute_verdict_matrix(self):
        self.assertEqual(phase_minus_one.compute_verdict(
            {"a": {"status": "OK"}, "b": {"status": "OK"}}), "OK")
        self.assertEqual(phase_minus_one.compute_verdict(
            {"a": {"status": "OK"}, "b": {"status": "CONFLICT"}}), "BLOCKED")
        self.assertEqual(phase_minus_one.compute_verdict(
            {"a": {"status": "OK"}, "b": {"status": "UNKNOWN"}}), "BLOCKED")
        self.assertEqual(phase_minus_one.compute_verdict(
            {"a": {"status": "WARN"}, "b": {"status": "PARTIAL"}}),
            "OK_WITH_WARNINGS")

    def test_run_check_smoke_with_real_ref(self):
        # 真档冒烟: data/stm32f103-ref.json 只读加载走通 run_check 全链
        out = phase_minus_one.run_check("I2C1", ["PC13"], [])
        self.assertIn(out["verdict"], ("OK", "OK_WITH_WARNINGS", "BLOCKED"))
        self.assertEqual(set(out["checks"]),
                         {"chip_support", "pin_conflict", "kb_coverage",
                          "known_issues"})


class RmLookupTests(unittest.TestCase):
    def test_search_peripheral(self):
        hits = rm_lookup.search_peripheral("i2c", MIN_REF)
        self.assertEqual([h["name"] for h in hits], ["I2C1"])

    def test_search_register(self):
        hits = rm_lookup.search_register("cr1", MIN_REF)
        self.assertEqual(hits[0]["peripheral"], "I2C1")
        self.assertEqual(hits[0]["register"], "CR1")

    def test_search_bit_by_name(self):
        hits = rm_lookup.search_bit("SMB", MIN_REF)
        self.assertEqual(hits[0]["bit"], "1")
        self.assertEqual(hits[0]["name"], "SMBALERT")

    def test_search_bit_by_position(self):
        hits = rm_lookup.search_bit("1", MIN_REF)
        self.assertTrue(any(h["bit"] == "1" for h in hits))

    def test_search_recipe(self):
        hits = rm_lookup.search_recipe("init", MIN_REF)
        self.assertEqual(hits[0]["peripheral"], "I2C1")

    def test_search_all_aggregates(self):
        out = rm_lookup.search_all("i2c", MIN_REF)
        self.assertEqual(out["query"], "i2c")
        self.assertEqual(len(out["peripherals"]), 1)
        self.assertEqual(len(out["recipes"]), 1)
        self.assertEqual(out["registers"], [])   # 查询是小写, 寄存器按大写匹配

    def test_load_ref_real_smoke(self):
        # 真档冒烟 (只读): 知识库在场且非空
        ref = rm_lookup.load_ref()
        self.assertIsInstance(ref.get("peripherals"), dict)
        self.assertGreaterEqual(len(ref["peripherals"]), 40)


class SvdToJsonParseTests(unittest.TestCase):
    def test_parse_bit_range(self):
        self.assertEqual(svd_to_json.parse_bit_range("[7:0]"), (0, 8))
        self.assertEqual(svd_to_json.parse_bit_range(" [31:16] "), (16, 16))

    def test_parse_dim_with_index_list_and_placeholder(self):
        elem = ET.fromstring(
            "<reg><dim>4</dim><dimIncrement>4</dimIncrement>"
            "<dimIndex>1,2,3,4</dimIndex><name>CCR%s</name></reg>")
        out = svd_to_json.parse_dim_element_group(elem)
        self.assertEqual([s for s, _ in out], ["1", "2", "3", "4"])
        self.assertEqual([i for _, i in out], [0, 1, 2, 3])

    def test_parse_dim_without_index_appends_numeric_suffix(self):
        elem = ET.fromstring(
            "<reg><dim>3</dim><dimIncrement>4</dimIncrement>"
            "<name>CCR</name></reg>")
        out = svd_to_json.parse_dim_element_group(elem)
        self.assertEqual([s for s, _ in out], ["_0", "_1", "_2"])

    def test_parse_dim_non_array(self):
        elem = ET.fromstring("<reg><name>CR1</name></reg>")
        self.assertEqual(svd_to_json.parse_dim_element_group(elem),
                         [(None, None)])


if __name__ == "__main__":
    unittest.main()
