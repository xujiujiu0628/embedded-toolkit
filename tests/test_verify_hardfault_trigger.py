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
        # 装配点接缝钉 (F-116/L-1 升级: 钉"三处全装配"而非"至少一处存在",
        # 漏装配 error 分支不再假绿; 手段仍是源码级, 行为面由
        # test_verify_failure_paths 系列 + 真机背书补)
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "scripts", "verify.py"),
            encoding="utf-8").read()
        self.assertEqual(src.count("hf_trigger = _hardfault_trigger("), 1)
        self.assertEqual(src.count('"trigger": hf_trigger'), 3)

    def test_marker_path_forwards_capture_text(self):
        # F-116/H-1 装配钉: marker 触发且有 [HF] PC= 行 → 必须把捕获文本
        # 递给层 2 (--fault-text - + input=), 否则 fault_site 永远缺席
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "scripts", "verify.py"),
            encoding="utf-8").read()
        self.assertIn('hf_cmd += ["--fault-text", "-"]', src)
        self.assertIn('hf_kw["input"] = captured_text', src)


if __name__ == "__main__":
    unittest.main()
