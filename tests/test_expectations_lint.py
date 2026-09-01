"""expectations_lint 回归 (R2 D 项, 2026-08-30).

E1~E9 规则逐条 + 真档冒烟 (现役 adc-oled 工程清单, 只读)。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import expectations_lint  # noqa: E402

ADC_OLED = r"<工作区根>\stm32f103-adc-oled"
ADC_OLED_EXP = os.path.join(ADC_OLED, ".workbench", "expectations.json")

VALID = {"expectations": [
    {"id": "FR-A", "desc": "boot ok", "texts": ["LED ON"]},
    {"id": "FR-B", "desc": "toggles", "patterns": [r"TGL \d+"],
     "capture_group": 1, "min": 1, "max": 10},
]}


class LintFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "expectations.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f, ensure_ascii=False)
        return expectations_lint.lint_file(self.path)

    def test_valid_clean(self):
        out = self._write(VALID)
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["item_count"], 2)

    def test_e1_unparseable(self):
        out = self._write("{not json")
        self.assertTrue(any(e.startswith("E1") for e in out["errors"]))

    def test_e1_top_level_list_rejected(self):
        out = self._write([{"id": "A"}])
        self.assertTrue(any(e.startswith("E1") for e in out["errors"]))

    def test_e1_empty_expectations(self):
        out = self._write({"expectations": []})
        self.assertTrue(any(e.startswith("E1") for e in out["errors"]))

    def test_e2_duplicate_id(self):
        out = self._write({"expectations": [
            {"id": "A", "desc": "d", "texts": ["x"]},
            {"id": "A", "desc": "d", "texts": ["y"]}]})
        self.assertTrue(any("E2" in e and "重复" in e for e in out["errors"]))

    def test_e2_missing_id(self):
        out = self._write({"expectations": [{"desc": "d", "texts": ["x"]}]})
        self.assertTrue(any(e.startswith("E2") for e in out["errors"]))

    def test_e3_missing_desc(self):
        out = self._write({"expectations": [{"id": "A", "texts": ["x"]}]})
        self.assertTrue(any(e.startswith("E3") for e in out["errors"]))

    def test_e4_both_texts_and_patterns(self):
        out = self._write({"expectations": [
            {"id": "A", "desc": "d", "texts": ["x"], "patterns": ["y"]}]})
        self.assertTrue(any(e.startswith("E4") for e in out["errors"]))

    def test_e4_neither(self):
        out = self._write({"expectations": [{"id": "A", "desc": "d"}]})
        self.assertTrue(any(e.startswith("E4") for e in out["errors"]))

    def test_e5_bad_regex(self):
        out = self._write({"expectations": [
            {"id": "A", "desc": "d", "patterns": ["TGL (\\d+"]}]})
        self.assertTrue(any(e.startswith("E5") for e in out["errors"]))

    def test_e6_xfail_without_reason(self):
        out = self._write({"expectations": [
            {"id": "A", "desc": "d", "texts": ["x"], "xfail": True}]})
        self.assertTrue(any(e.startswith("E6") for e in out["errors"]))

    def test_e7_capture_group_with_texts(self):
        out = self._write({"expectations": [
            {"id": "A", "desc": "d", "texts": ["x"], "capture_group": 1}]})
        self.assertTrue(any(e.startswith("E7") for e in out["errors"]))

    def test_e7_capture_group_zero(self):
        out = self._write({"expectations": [
            {"id": "A", "desc": "d", "patterns": ["(x)"], "capture_group": 0}]})
        self.assertTrue(any(e.startswith("E7") for e in out["errors"]))

    def test_e8_nan_min(self):
        # Python json 接受 NaN 字面量 — 正是 M1 发现的"恒 pass"漏洞入口
        out = self._write('{"expectations": [{"id": "A", "desc": "d", '
                          '"patterns": ["(\\\\d+)"], "capture_group": 1, '
                          '"min": NaN}]}')
        self.assertTrue(any(e.startswith("E8") for e in out["errors"]))

    def test_e9_min_greater_than_max(self):
        out = self._write({"expectations": [
            {"id": "A", "desc": "d", "patterns": ["(\\d+)"],
             "capture_group": 1, "min": 10, "max": 1}]})
        self.assertTrue(any(e.startswith("E9") for e in out["errors"]))

    def test_xfail_items_produce_warning(self):
        out = self._write({"expectations": [
            {"id": "A", "desc": "d", "texts": ["x"], "xfail": True,
             "xfail_reason": "not implemented"}]})
        self.assertEqual(out["errors"], [])
        self.assertTrue(any("xfail" in w for w in out["warnings"]))

    def test_missing_file_is_error(self):
        out = expectations_lint.lint_file(os.path.join(self.tmp, "nope.json"))
        self.assertTrue(any(e.startswith("E0") for e in out["errors"]))

    def test_cli_exit_codes_and_json(self):
        # error → 退出码 1; --json 输出带 verdict
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{broken")
        r = subprocess.run(
            [sys.executable,
             os.path.join(os.path.dirname(os.path.dirname(
                 os.path.abspath(__file__))), "scripts", "expectations_lint.py"),
             self.path, "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 1)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["verdict"], "error")

    def test_json_output_utf8_regardless_of_console(self):
        # F-025 回归: 曾随环境——Windows GBK 控制台下中文字段以 GBK 字节落管道,
        # 父进程按 utf-8 解码崩溃。脚本自身强制 stdout/stderr UTF-8 后,
        # 即使被强制成 GBK 环境, --json 输出仍必须是合法 UTF-8 JSON。
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{broken")
        env = dict(os.environ, PYTHONIOENCODING="gbk")
        r = subprocess.run(
            [sys.executable,
             os.path.join(os.path.dirname(os.path.dirname(
                 os.path.abspath(__file__))), "scripts", "expectations_lint.py"),
             self.path, "--json"],
            capture_output=True, text=True, encoding="utf-8",
            env=env, timeout=60)
        self.assertEqual(r.returncode, 1)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["verdict"], "error")

    @unittest.skipUnless(os.path.isfile(ADC_OLED_EXP), "adc-oled 工程不在场")
    def test_real_adc_oled_expectations_clean(self):
        # 真档冒烟: 现役工程的清单必须过 lint (只读, 不触硬件)
        out = expectations_lint.lint_file(ADC_OLED_EXP)
        self.assertEqual(out["errors"], [], out["errors"])
        self.assertGreaterEqual(out["item_count"], 1)


if __name__ == "__main__":
    unittest.main()
