"""契约 fixture 入库真伪测试 (F-038)。

tests/fixtures/contract/ 是 .workbench 契约的"最小合法样例 + 活规范":
config.json + expectations.json 覆盖期望条目全部九个字段 (id / desc /
texts / patterns / xfail / xfail_reason / capture_group / min / max),
必须同时过三关 —— lint 全绿 / loader 能吃 / 四态判定语义正确。
schema 演化时 fixture 同步改, 本文件的 diff 即评审点。

背景 (F-040): README「5 分钟上手」示例曾用单数 "pattern" 键, loader 与
lint 均只认复数 "patterns" (非空字符串数组) —— 照抄示例的用户在 verify
第一步即收到 "期望清单非法"。fixture 按 loader 真实接受的形态入库, 并以
test_singular_pattern_key_rejected 钉死该差异防回潮。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402  (import 期读 machine.json, 缺失时走 example 回退链)
import wb_runtime  # noqa: E402
from expectations_lint import lint_file  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "contract")
CONFIG_FIXTURE = os.path.join(FIXTURE_DIR, "config.json")
EXPECTATIONS_FIXTURE = os.path.join(FIXTURE_DIR, "expectations.json")


def _make_tmp_workspace():
    """fixture 拷进临时工程 .workbench/, 供 loader 族消费 (纯内存, 不触硬件)。"""
    ws = tempfile.mkdtemp()
    wb = os.path.join(ws, ".workbench")
    os.makedirs(wb)
    for name in ("config.json", "expectations.json"):
        shutil.copy(os.path.join(FIXTURE_DIR, name), os.path.join(wb, name))
    return ws


class ConfigFixtureTests(unittest.TestCase):
    def test_matches_documented_defaults(self):
        """fixture 字段 = README「5 分钟上手」第 1 步公示值 (契约即文档,
        双处漂移由本测试拦截)。"""
        with open(CONFIG_FIXTURE, encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["toolkit_min_version"], "0.1")
        self.assertEqual(cfg["builder"], "gcc")
        self.assertEqual(cfg["gcc"], {"project": "Makefile", "target": "main",
                                      "log_dir": ".workbench/build"})
        self.assertEqual(cfg["capture"], {"backend": "rtt", "port": 19021,
                                          "sram_base": "0x20000000", "sram_size": 2048,
                                          "id": "SEGGER RTT", "boot_delay_ms": 300})

    def test_verify_load_config_consumes(self):
        """loader 能吃: verify.load_config 无 ConfigError, 关键段原样可达。"""
        ws = _make_tmp_workspace()
        try:
            cfg = verify.load_config(ws)
            self.assertEqual(cfg["builder"], "gcc")
            self.assertEqual(cfg["capture"]["backend"], "rtt")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_gcc_section_via_runtime_loader(self):
        """运行时配置链能吃: load_project_config 按 skill 取段 (F-029 T5 规范版)。"""
        ws = _make_tmp_workspace()
        try:
            gcc = wb_runtime.load_project_config(ws, skill="gcc")
            self.assertEqual(gcc.get("target"), "main")
            self.assertEqual(gcc.get("project"), "Makefile")
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class ExpectationsFixtureTests(unittest.TestCase):
    def test_lint_clean_with_single_xfail_warning(self):
        """lint 全绿; 唯一 warning 是 xfail 提示 (F-026 钉的'唯一合法 warning')。"""
        out = lint_file(EXPECTATIONS_FIXTURE)
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["item_count"], 3)
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("xfail", out["warnings"][0])

    def test_loader_accepts_fixture(self):
        ws = _make_tmp_workspace()
        try:
            items = verify.load_expectations(ws)
            self.assertEqual([i["id"] for i in items],
                             ["FR-SYS-01", "FR-ADC-02", "FR-FUTURE-1"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_four_state_semantics_on_fixture(self):
        """fixture 即活规范: 全信号 → pass/pass/xpass (xpass 强制判红);
        缺 TODO → xfail (verdict ok); ADC 低于下限 → fail (数值断言真起作用)。"""
        ws = _make_tmp_workspace()
        try:
            items = verify.load_expectations(ws)
            full = verify.evaluate_expectations(
                "=== boot ===\n[init] CLK OK\nmv=3192\nTODO", items)
            self.assertEqual({r["id"]: r["status"] for r in full["results"]},
                             {"FR-SYS-01": "pass", "FR-ADC-02": "pass",
                              "FR-FUTURE-1": "xpass"})
            self.assertEqual(full["verdict"], "fail")
            self.assertEqual(full["xpass_ids"], ["FR-FUTURE-1"])

            no_todo = verify.evaluate_expectations(
                "=== boot ===\n[init] CLK OK\nmv=3192", items)
            self.assertEqual({r["id"]: r["status"] for r in no_todo["results"]},
                             {"FR-SYS-01": "pass", "FR-ADC-02": "pass",
                              "FR-FUTURE-1": "xfail"})
            self.assertEqual(no_todo["verdict"], "ok")

            below = verify.evaluate_expectations("mv=2500", items)
            adc = [r for r in below["results"] if r["id"] == "FR-ADC-02"][0]
            self.assertEqual(adc["status"], "fail")
            self.assertIn("min", adc.get("detail", ""))
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_singular_pattern_key_rejected(self):
        """F-040 回归钉: 单数 "pattern" 键不被 loader 接受 (README 曾示错误例,
        2026-09-02 已修正为复数)。若未来 loader 决定兼容单数, 应显式改本钉。"""
        ws = _make_tmp_workspace()
        try:
            path = os.path.join(ws, ".workbench", "expectations.json")
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            doc["expectations"][1] = {"id": "FR-BAD", "desc": "单数键样例",
                                      "pattern": r"mv=(\d{4})", "capture_group": 1,
                                      "min": 1, "max": 2}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
            with self.assertRaises(verify.ExpectationError):
                verify.load_expectations(ws)
        finally:
            shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
