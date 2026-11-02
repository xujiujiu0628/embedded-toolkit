r"""F-246: verify `_run_judgement` 的 HardFault / 物理门控 / 四态判定补测。

## 覆盖对象

`verify.py` 91% 的尾部：HardFault marker/auto 两种触发与诊断失败/异常、
物理门控 TIMING_FAIL、manifest 与 legacy 两种判定、capture 空兜底。
"""
import io
import json
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


def _args(no_flash=False, require_tgl=False):
    return SimpleNamespace(no_flash=no_flash, json=True, task_origin="manual",
                           gate_run=False, require_tgl=require_tgl)


class JudgementTests(unittest.TestCase):
    def _run(self, *, captured_text="", captured_lines=None, trigger=None,
             hf_proc=None, hf_exc=None, physical=None, expect_mode="legacy",
             expectations=None, eval_result=None, verify_result=None,
             config=None, args=None):
        result = {"steps": {"flash": {"status": "ok"}}, "status": "ok"}
        args = args or _args()

        def _hf_run(*_a, **_k):
            if hf_exc:
                raise hf_exc
            return hf_proc

        old_sub = verify.subprocess
        verify.subprocess = SimpleNamespace(
            run=_hf_run, TimeoutExpired=TimeoutError)
        try:
            with mock.patch.object(verify, "_hardfault_trigger", return_value=trigger), \
                    mock.patch.object(verify, "_esp_backend_mode", return_value=False), \
                    mock.patch.object(verify, "hardfault_budget_s", return_value=10), \
                    mock.patch.object(verify, "step_physical_gate",
                                      return_value=physical or {"status": "skipped"}), \
                    mock.patch.object(verify, "evaluate_expectations",
                                      return_value=eval_result or {
                                          "verdict": "ok", "results": [],
                                          "xpass_ids": [], "records": []}), \
                    mock.patch.object(verify, "verify",
                                      return_value=verify_result or {
                                          "status": "ok", "matched": [], "missing": []}), \
                    mock.patch.object(verify, "cli_expectations", return_value=[]), \
                    mock.patch.object(verify, "_empty_capture_note",
                                      return_value="[empty] "), \
                    redirect_stdout(io.StringIO()):
                verify._run_judgement(
                    args, config or {}, result, captured_text, captured_lines or [],
                    1, [], "desc", expectations, expect_mode, time.time())
        finally:
            verify.subprocess = old_sub
        return result

    def _proc(self, payload=None, rc=0, stderr=""):
        return SimpleNamespace(returncode=rc,
                               stdout=json.dumps(payload) if payload is not None else "",
                               stderr=stderr)

    def test_marker_hardfault_detected(self):
        result = self._run(
            captured_text="=== HARDFAULT ===", trigger="marker",
            hf_proc=self._proc({"fault_type": "BusFault", "diagnosis": "d",
                                "registers": {}, "fault_registers": {},
                                "resolved": {}, "fault_site": {"pc": "0x1"}}))
        self.assertEqual(result["status"], "hardfault")
        hf = result["steps"]["hardfault"]
        self.assertEqual(hf["status"], "hardfault_detected")
        self.assertTrue(hf["review_needed"])
        self.assertIn("fault_site", hf)

    def test_marker_auto_no_fault(self):
        result = self._run(
            captured_text="=== HARDFAULT ===", trigger="marker",
            hf_proc=self._proc({"fault_type": "no_fault"}))
        self.assertEqual(result["steps"]["hardfault"]["status"], "checked_no_fault")
        # marker 触发本身即判 hardfault（层 1 标记优先于层 2 的 no_fault）
        self.assertEqual(result["status"], "hardfault")

    def test_diagnosis_failure(self):
        result = self._run(trigger="empty_fallback",
                           hf_proc=self._proc(rc=1, stderr="boom"))
        self.assertEqual(result["steps"]["hardfault"]["status"], "error")
        self.assertIn("Diagnosis failed", result["steps"]["hardfault"]["message"])

    def test_diagnosis_exception(self):
        result = self._run(trigger="empty_fallback", hf_exc=OSError("spawn"))
        self.assertEqual(result["steps"]["hardfault"]["status"], "error")
        self.assertIn("spawn", result["steps"]["hardfault"]["message"])

    def test_timing_fail_gate(self):
        result = self._run(physical={"status": "timing_fail", "error": "too fast"})
        self.assertEqual(result["status"], "timing_fail")
        self.assertEqual(result["steps"]["verify"]["status"], "fail")

    def test_manifest_judgement(self):
        ev = {"verdict": "fail",
              "results": [{"id": "A", "status": "pass"},
                          {"id": "B", "status": "fail"}],
              "xpass_ids": [], "records": [{"id": "A", "x": "1"}]}
        result = self._run(expect_mode="manifest", expectations=[{"id": "A"}],
                           eval_result=ev)
        self.assertEqual(result["steps"]["verify"]["status"], "fail")
        self.assertEqual(result["records"], [{"id": "A", "x": "1"}])

    def test_legacy_judgement_with_empty_capture_note(self):
        result = self._run(
            captured_text="", captured_lines=[],
            verify_result={"status": "fail", "matched": [], "missing": ["A"],
                           "description": "orig"})
        self.assertTrue(result["steps"]["verify"]["description"].startswith("[empty] "))

    def test_physical_gate_probe_error_fails_closed(self):
        result = self._run(physical={"status": "probe_error", "error": "no probe"})
        self.assertEqual(result["status"], "physical_gate_failed")


if __name__ == "__main__":
    unittest.main()
