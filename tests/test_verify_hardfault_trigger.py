"""F-115 (B1): HardFault 诊断触发路径归因钉 (spec 2026-09-11-rtt-hardfault §3.2)

verify Step 4b 的触发本有两条路: C 级显式标记 (主路径) 与"烧过但空输出"
(真兜底)。此前 JSON 不区分——RTT 工程缺 C 级 handler 时, 空捕获兜底与
真 HardFault 不可事后审计。trigger 字段把归因落进契约: "marker" |
"empty_fallback" | None。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


class HardfaultTriggerTests(unittest.TestCase):
    def test_marker_wins_even_with_lines(self):
        # 有输出 + 含标记 → 主路径 (RTT 工程 B1 回填后走这条)
        self.assertEqual(
            verify._hardfault_trigger("boot ok\n=== HARDFAULT ===\nCFSR=...",
                                       False, True), "marker")

    def test_empty_fallback_when_flashed(self):
        self.assertEqual(
            verify._hardfault_trigger("", True, True), "empty_fallback")

    def test_no_trigger_when_not_flashed(self):
        # 08-12 回归钉: --no-build/--no-flash 空输出是预期, 不触发不判
        self.assertIsNone(verify._hardfault_trigger("", True, False))

    def test_no_trigger_normal_run(self):
        self.assertIsNone(verify._hardfault_trigger("all ok", False, True))

    def test_case_sensitive_no_false_positive(self):
        # 固件正文小写 hardfault 字样 (如日志字符串) 不得误触主路径
        self.assertIsNone(
            verify._hardfault_trigger("counter hardfault handled", False, True))

    def test_marker_takes_precedence_over_fallback(self):
        # 标记与空捕获理论上互斥; 若同帧出现 (截断等病态输入), 归因取
        # marker——它携带的信息更强
        self.assertEqual(
            verify._hardfault_trigger("=== HARDFAULT ===", True, True),
            "marker")


class HardfaultStepContractTests(unittest.TestCase):
    """verify 主流程内 steps.hardfault 携带 trigger 的契约钉 (mock 诊断子进程)。"""

    def test_steps_hardfault_carries_trigger(self):
        # 纯函数与装配点的接缝: 装配代码把 _hardfault_trigger 结果写进
        # steps.hardfault["trigger"]——用源码钉防装配漂移 (断言钉行为面:
        # 调用点存在且值来自纯函数, 非硬编码)
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "scripts", "verify.py"),
            encoding="utf-8").read()
        self.assertIn("hf_trigger = _hardfault_trigger(", src)
        self.assertIn('"trigger": hf_trigger', src)


if __name__ == "__main__":
    unittest.main()
