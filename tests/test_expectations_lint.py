"""expectations_lint 回归 (R2 D 项, 2026-08-30).

E1~E9 规则逐条 + 合成全字段冒烟。

F-026 订正: 原"真档冒烟"硬编码维护者本机 adc-oled 路径, 历史重写后变占位符
恒跳过 (本机亦失效)——已改 tempfile 合成清单 (覆盖 texts/patterns/capture_group/
min/max/xfail 全字段面); 真档冒烟改为环境变量 ETK_SMOKE_EXPECTATIONS opt-in。
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

SMOKE_ENV = "ETK_SMOKE_EXPECTATIONS"  # 真档冒烟 opt-in: 指路径则 lint 之 (F-026)

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


class SyntheticSmokeTests(unittest.TestCase):
    """F-026: 冒烟从"维护者本机真档"改为"tempfile 合成全字段清单"——任何
    机器任何检出都应跑通; 真档冒烟保留能力, 经 ETK_SMOKE_EXPECTATIONS opt-in。"""

    FULL_FEATURED = {"expectations": [
        {"id": "FR-SYS-01", "desc": "启动横幅", "texts": ["=== boot ==="]},
        {"id": "FR-ADC-02", "desc": "毫伏读数", "patterns": [r"mv=(\d{4})"],
         "capture_group": 1, "min": 0, "max": 3300},
        {"id": "FR-TGL-03", "desc": "已知缺陷留痕", "patterns": [r"TGL \d+"],
         "xfail": True, "xfail_reason": "L3 回绕 deferred, 见台账"},
    ]}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_full_featured_manifest_clean_xfail_warned(self):
        p = os.path.join(self.tmp, "expectations.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.FULL_FEATURED, f, ensure_ascii=False)
        out = expectations_lint.lint_file(p)
        self.assertEqual(out["errors"], [], out["errors"])
        self.assertEqual(out["item_count"], 3)
        self.assertEqual(len(out["warnings"]), 1,
                         "xfail 提示是唯一合法 warning: " + str(out["warnings"]))
        self.assertIn("xfail", out["warnings"][0])

    @unittest.skipUnless(os.path.isfile(os.environ.get(SMOKE_ENV, "")),
                         f"未设 {SMOKE_ENV} 真档冒烟路径")
    def test_real_project_expectations_clean_opt_in(self):
        out = expectations_lint.lint_file(os.environ[SMOKE_ENV])
        self.assertEqual(out["errors"], [], out["errors"])
        self.assertGreaterEqual(out["item_count"], 1)


if __name__ == "__main__":
    unittest.main()
