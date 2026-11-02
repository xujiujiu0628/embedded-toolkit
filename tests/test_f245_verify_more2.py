r"""F-245: verify 的命令超时 / 审计落盘失败 / 模式未命中 / 信封 / 人读输出补测。

## 覆盖对象

`scripts/verify.py` 剩余零散分支：`run_cmd` 超时、`append_audit_entry`
落盘失败告警、`verify()` 的 pattern 未命中、`main` 的 BaseException 信封、
`_log_feedback_event` 的 JSON 解析失败、`_output` 人读模式的 Found/Missing/
XPASS/captured 截断。
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


class RunCmdTimeoutTests(unittest.TestCase):
    def test_timeout_returns_error(self):
        old = verify.subprocess
        verify.subprocess = SimpleNamespace(
            run=lambda *a, **k: (_ for _ in ()).throw(TimeoutError()),
            TimeoutExpired=TimeoutError)
        try:
            result = verify.run_cmd(["x"], timeout=1)
        finally:
            verify.subprocess = old
        self.assertEqual(result["status"], "error")
        self.assertIn("timed out", result["message"])


class AuditFailureTests(unittest.TestCase):
    def test_audit_write_failure_warns(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, ".workbench"))
            # 让 state 成为普通文件 → makedirs 抛 OSError
            with open(os.path.join(ws, ".workbench", "state"), "w", encoding="utf-8") as fh:
                fh.write("x")
            err = io.StringIO()
            with redirect_stderr(err):
                verify.append_audit_entry(ws, "manual", "build", "ok", ["make"])
        self.assertIn("audit 落盘失败", err.getvalue())


class VerifyPatternMissTests(unittest.TestCase):
    def test_pattern_missing_recorded(self):
        result = verify.verify("no match here", [], "", expect_patterns=[r"TGL \d+"])
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["missing_patterns"], [r"TGL \d+"])


class MainEnvelopeTests(unittest.TestCase):
    def test_uncaught_exception_goes_to_envelope(self):
        args = SimpleNamespace(doctor=False, junit_xml=None, json=True)
        with mock.patch.object(verify, "_parse_args", return_value=args), \
                mock.patch.object(verify, "_run_pipeline",
                                  side_effect=RuntimeError("boom")), \
                mock.patch.object(verify, "_fail_with_envelope") as env:
            verify.main()
        env.assert_called_once()


class FeedbackLogJsonErrorTests(unittest.TestCase):
    def test_bad_json_stdout_is_tolerated(self):
        def _run(*_a, **_k):
            return SimpleNamespace(returncode=0, stdout="not json", stderr="")

        old = verify.subprocess
        verify.subprocess = SimpleNamespace(run=_run, TimeoutExpired=TimeoutError)
        try:
            result = verify._log_feedback_event({"status": "ok", "steps": {}}, False)
        finally:
            verify.subprocess = old
        self.assertTrue(result["logged"])


class OutputHumanTests(unittest.TestCase):
    def test_human_output_prints_details(self):
        result = {
            "status": "fail",
            "steps": {
                "build": {"status": "ok"},
                "analyze": {"status": "ok"},
                "flash": {"status": "ok"},
                "capture": {"status": "ok"},
                "verify": {
                    "status": "fail",
                    "matched": ["A"],
                    "missing": ["B"],
                    "results": [{"id": "A", "status": "pass"},
                                {"id": "C", "status": "xfail", "detail": "d"},
                                {"id": "D", "status": "xpass"}],
                    "xpass_ids": ["D"],
                },
                "physical_gate": {"status": "skipped"},
            },
            "captured_output": "x" * 600,
            "elapsed_sec": 1.2,
        }
        out = io.StringIO()
        with redirect_stdout(out):
            verify._output(result, as_json=False)
        text = out.getvalue()
        self.assertIn("Found:", text)
        self.assertIn("Missing:", text)
        self.assertIn("[PASS] A", text)
        self.assertIn("[XFAIL] C", text)
        self.assertIn("XPASS 落地信号", text)
        self.assertIn("more chars", text)
        self.assertIn("Verdict: FAIL", text)


if __name__ == "__main__":
    unittest.main()
