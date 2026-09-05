r"""physical_gate 单元测试 (F-057) — 物理门控逻辑的真单测（拆分前的盲区）.

拆分前 step_physical_gate 藏在 verify.py 里, 需要真机才能走到 —— TCL 生成、
PHYS_GATE_RESULT 解析、判定数学（measured/deviation/timing_fail）与各
probe_error 分支从未被真实断言过。

注入方式: mock physical_gate.subprocess.Popen → 假 OpenOCD（communicate 返回
含 PHYS_GATE_RESULT 行的可编程输出）; workspace 用临时目录, TCL 落盘可检查。
"""

import glob
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import physical_gate  # noqa: E402


class _FakeProc:
    def __init__(self, stdout="", stderr=""):
        self._stdout, self._stderr = stdout, stderr
        self.killed = False

    def communicate(self, timeout=None):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


_GOOD = "PHYS_GATE_RESULT samples=100 edges=40 elapsed_ms=10000 fail_reads=0"

_CFG = {"enable": True, "address": "0x4001100C", "mask": 0x2000,
        "expected_toggles_per_sec": 4.0, "measurement_window_ms": 10000,
        "min_edges": 8}


class PhysicalGateTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def _run(self, stdout="", stderr="", cfg=None, sleeps=None):
        sleeps = sleeps if sleeps is not None else []
        proc = _FakeProc(stdout, stderr)

        def fake_popen(cmd, **kwargs):
            self._cmd = cmd
            return proc

        with mock.patch.object(physical_gate.subprocess, "Popen", fake_popen), \
                mock.patch.object(physical_gate.time, "sleep",
                                  lambda s: sleeps.append(s)):
            out = physical_gate.step_physical_gate(cfg or _CFG, timeout=10,
                                                   workspace=self.ws)
        return out

    def _tcl_text(self):
        files = glob.glob(os.path.join(
            self.ws, ".workbench", "build", "physical_gate_*.tcl"))
        self.assertEqual(len(files), 1, "恰好生成一份 TCL 探测脚本")
        with open(files[0], encoding="utf-8") as f:
            return f.read()

    def test_disabled_is_skipped_with_zero_overhead(self):
        guard = mock.Mock(side_effect=AssertionError("禁用态不得拉起任何子进程"))

        with mock.patch.object(physical_gate.subprocess, "Popen", guard):
            out = physical_gate.step_physical_gate({"enable": False},
                                                   timeout=10, workspace=self.ws)
        self.assertEqual(out, {"status": "skipped"})
        guard.assert_not_called()

    def test_tcl_generation_pin(self):
        """TCL 内容钉: 预热节奏逻辑 / 初始化边沿告警 / 测量窗口 / 结果行格式"""
        self._run(stdout=_GOOD)
        tcl = self._tcl_text()
        self.assertIn("read_memory 0x4001100C 32 1", tcl)
        # mask 是 int, f-string 插值为十进制 (0x2000 → 8192, 与原实现逐字节一致)
        self.assertIn("[lindex $vals 0] & 8192", tcl)
        self.assertIn("最多等 4000ms", tcl)
        self.assertIn("复位后 led_init 会有 1 个初始化边沿", tcl,
                      "初始化边沿不能当闪烁信号的告警必须随 TCL 生成")
        self.assertIn('PHYS_GATE_RESULT samples=$samples edges=$edges', tcl)
        self.assertIn("sleep 100", tcl)

    def test_ok_verdict_math(self):
        out = self._run(stdout=_GOOD)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["measured_toggles_per_sec"], 4.0)
        self.assertEqual(out["deviation"], 0.0)
        self.assertEqual(out["edges"], 40)

    def test_timing_fail_deviation(self):
        out = self._run(
            stdout="PHYS_GATE_RESULT samples=100 edges=48 elapsed_ms=10000 fail_reads=0")
        self.assertEqual(out["status"], "timing_fail")
        self.assertEqual(out["measured_toggles_per_sec"], 4.8)
        self.assertIn("Timing constraints violated", out["error"])

    def test_insufficient_samples(self):
        out = self._run(
            stdout="PHYS_GATE_RESULT samples=100 edges=2 elapsed_ms=10000 fail_reads=0")
        self.assertEqual(out["status"], "insufficient_samples")
        self.assertEqual(out["edges"], 2)

    def test_probe_error_no_steady_blink(self):
        out = self._run(
            stdout="PHYS_GATE_RESULT samples=0 edges=0 elapsed_ms=0 fail_reads=0")
        self.assertEqual(out["status"], "probe_error")
        self.assertIn("no steady blink pattern", out["error"])

    def test_probe_error_too_many_failed_reads(self):
        out = self._run(
            stdout="PHYS_GATE_RESULT samples=10 edges=9 elapsed_ms=2500 fail_reads=8")
        self.assertEqual(out["status"], "probe_error")
        self.assertEqual(out["error"], "too many failed reads: 8/10")

    def test_no_result_line_retries_three_times(self):
        sleeps = []
        out = self._run(stdout="", stderr="OpenOCD boot log", sleeps=sleeps)
        self.assertEqual(out["status"], "probe_error")
        self.assertIn("no PHYS_GATE_RESULT line", out["error"])
        self.assertIn("OpenOCD boot log", out["stderr_tail"])
        self.assertEqual(len(sleeps), 2, "3 次重试间隔仅 2 次")


if __name__ == "__main__":
    unittest.main()
