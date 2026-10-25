"""物理门控 fail-closed 回归。

门控显式启用后, 探测失败或样本不足表示"物理时序未被证明", 不能沿用
文本判定的 PASS。最小复现走 expected<=0 的既有 probe_error 前置守卫,
不启动 OpenOCD。
"""
import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


class PhysicalGateFailClosedTests(unittest.TestCase):
    def _judge(self, physical=None, expect_mode="legacy"):
        result = {"steps": {}}
        args = SimpleNamespace(require_tgl=False, no_flash=True)
        patch = (mock.patch.object(verify, "step_physical_gate",
                                   return_value=physical)
                 if physical is not None else mock.patch.object(
                     verify, "step_physical_gate",
                     wraps=verify.step_physical_gate))
        expectations = ([{"id": "BOOT", "texts": ["BOOT ok"]}]
                        if expect_mode == "manifest" else None)
        with patch:
            verify._run_judgement(
                args,
                {"physical_gate": {"enable": True,
                                   "expected_toggles_per_sec": 0}},
                result, "BOOT ok", ["BOOT ok"], 10, ["BOOT ok"], "",
                expectations, expect_mode, time.time())
        return result

    def test_probe_error_makes_whole_run_fail(self):
        result = self._judge()
        self.assertEqual(result["steps"]["physical_gate"]["status"],
                         "probe_error")
        self.assertEqual(result["status"], "physical_gate_failed")

    def test_insufficient_samples_makes_whole_run_fail(self):
        result = self._judge({"status": "insufficient_samples",
                              "edges": 2, "min_edges": 8})
        self.assertEqual(result["status"], "physical_gate_failed")

    def test_manifest_results_include_physical_gate_failure(self):
        result = self._judge({"status": "probe_error", "error": "no probe"},
                             expect_mode="manifest")
        rows = result["steps"]["verify"]["results"]
        self.assertEqual(rows[-1]["id"], "PHYSICAL-GATE")
        self.assertEqual(rows[-1]["status"], "fail")
        self.assertEqual(result["steps"]["verify"]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
