r"""F-244: verify.py 的脚本执行封装 / 构建分析步骤 / 信封与预检补测。

## 覆盖对象

`scripts/verify.py` 此前 84% 覆盖（2026-11-02 实测）：`run_py` 的四态
（成功/无输出/超时/坏 JSON）、`step_build`/`step_analyze` 的 keil 桥分支、
`cli_expectations`、`_release_hw_lease`、`_fail_fast_on_bad_patterns`、
`_run_doctor` 的 strict 出口、`_fail_with_envelope` 与 `_prepare_context` 的
三条早退未执行。

## 夹具

`subprocess` 用直接赋值替身（避免 test_stub_ratchet 的 B 式判据）；
`_keil_bridge_paths` / `run_py` / `doctor_report` 等模块引用替换；不接硬件。
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


def _run_py_with(proc=None, exc=None):
    calls = []

    def _run(cmd, **_kw):
        calls.append(cmd)
        if exc:
            raise exc
        return proc

    old = verify.subprocess
    verify.subprocess = SimpleNamespace(run=_run, TimeoutExpired=TimeoutError)
    try:
        return verify.run_py("script.py", ["--x"], timeout=5), calls
    finally:
        verify.subprocess = old


class RunPyTests(unittest.TestCase):
    def test_json_output_parsed(self):
        result, _ = _run_py_with(SimpleNamespace(stdout='{"status": "ok"}',
                                                 stderr="", returncode=0))
        self.assertEqual(result, {"status": "ok"})

    def test_no_output_is_error(self):
        result, _ = _run_py_with(SimpleNamespace(stdout="", stderr="boom", returncode=1))
        self.assertEqual(result["status"], "error")
        self.assertIn("no output", result["message"])
        self.assertIn("boom", result["stderr"])

    def test_timeout_is_error(self):
        result, _ = _run_py_with(exc=TimeoutError())
        self.assertIn("timed out", result["message"])

    def test_bad_json_is_error(self):
        result, _ = _run_py_with(SimpleNamespace(stdout="{bad", stderr="", returncode=0))
        self.assertEqual(result["status"], "error")
        self.assertIn("JSON parse error", result["message"])
        self.assertEqual(result["raw_output"], "{bad")


class StepBuildTests(unittest.TestCase):
    def test_gcc_build_path(self):
        calls = []

        def _run_py(script, args, timeout=120):
            calls.append((script, args, timeout))
            return {"status": "ok"}

        with mock.patch.object(verify, "run_py", side_effect=_run_py), \
                mock.patch.object(verify, "GCC_BUILD", "gcc_build.py"):
            result = verify.step_build({"gcc": {"project": "p", "target": "t"}})
        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(calls[0][0], "gcc_build.py")
        self.assertEqual(calls[0][2], 300)

    def test_keil_build_path(self):
        calls = []

        def _run_py(script, args, timeout=120):
            calls.append((script, args, timeout))
            return {"status": "ok"}

        with mock.patch.object(verify, "run_py", side_effect=_run_py), \
                mock.patch.object(verify, "_keil_bridge_paths",
                                  return_value=("keil_build.py", "keil_analyze.py")):
            result = verify.step_build({"keil": {"project": "b.uvprojx"}}, builder="keil")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls[0][0], "keil_build.py")
        self.assertIn("b.uvprojx", calls[0][1])


class StepAnalyzeTests(unittest.TestCase):
    def test_gcc_skips_kb_analysis(self):
        result = verify.step_analyze("log", builder="gcc",
                                     build_metrics={"errors": 1, "warnings": 2})
        self.assertEqual(result["summary"]["errors"], 1)
        self.assertEqual(result["summary"]["warnings"], 2)

    def test_keil_uses_analyze_bridge(self):
        with mock.patch.object(verify, "_keil_bridge_paths",
                               return_value=("kb.py", "analyze.py")), \
                mock.patch.object(verify, "run_py", return_value={"status": "ok"}) as spy:
            result = verify.step_analyze("log", builder="keil")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(spy.call_args[0][0], "analyze.py")


class CliExpectationsTests(unittest.TestCase):
    def test_texts_patterns_and_tgl(self):
        items = verify.cli_expectations(["a", "b"], [r"x\d"], True)
        ids = [i["id"] for i in items]
        self.assertEqual(ids, ["CLI-TEXT-00", "CLI-TEXT-01", "CLI-PAT-00", "CLI-REQUIRE-TGL"])
        self.assertEqual(items[-1]["patterns"], [r"TGL \d+"])

    def test_empty(self):
        self.assertEqual(verify.cli_expectations(None, None, False), [])


class VerifyFunctionTests(unittest.TestCase):
    def test_empty_contract_fails(self):
        result = verify.verify("anything", [], None)
        self.assertEqual(result["status"], "fail")
        self.assertIn("<no assertions configured>", result["missing"])

    def test_matched_and_missing(self):
        result = verify.verify("LED ON TGL 3", ["LED ON", "NOPE"], ["TGL \\d+"])
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["matched"], ["LED ON"])
        self.assertEqual(result["missing"], ["NOPE"])
        self.assertEqual(result["missing_patterns"], [])

    def test_all_found(self):
        result = verify.verify("LED ON", ["LED ON"])
        self.assertEqual(result["status"], "ok")


class ReleaseLeaseTests(unittest.TestCase):
    def test_no_lease_is_noop(self):
        verify._release_hw_lease(None)

    def test_lease_not_ok_is_noop(self):
        verify._release_hw_lease({"ok": False})

    def test_release_failure_warns(self):
        err = io.StringIO()
        with mock.patch.object(verify, "hw_lease") as hw, redirect_stderr(err):
            hw.release.return_value = {"ok": False, "error": "denied"}
            verify._release_hw_lease({"ok": True})
        self.assertIn("设备锁释放失败", err.getvalue())


class BadPatternTests(unittest.TestCase):
    def test_bad_config_pattern_raises(self):
        with mock.patch.object(verify, "load_expectations", return_value=None):
            with self.assertRaises(verify.BadPatternError) as ctx:
                verify._fail_fast_on_bad_patterns(
                    {"verify": {"expect_patterns": ["["]}})
        self.assertIn("expect_patterns", str(ctx.exception))

    def test_bad_manifest_raises(self):
        with mock.patch.object(verify, "load_expectations",
                               side_effect=verify.ExpectationError("E5 bad")):
            with self.assertRaises(verify.BadPatternError):
                verify._fail_fast_on_bad_patterns({})

    def test_valid_patterns_pass(self):
        with mock.patch.object(verify, "load_expectations", return_value=None):
            verify._fail_fast_on_bad_patterns({"verify": {"expect_patterns": [r"TGL \d+"]}})


class RunDoctorTests(unittest.TestCase):
    def _args(self, strict=False, as_json=False):
        return SimpleNamespace(project=None, json=as_json, strict=strict)

    def test_strict_failure_exits_one(self):
        with mock.patch.object(verify, "doctor_report", return_value={"summary": {"fail": 1}}), \
                mock.patch.object(verify, "strict_exit_code", return_value=1), \
                mock.patch.object(verify, "_print_doctor"):
            with self.assertRaises(SystemExit) as ctx:
                verify._run_doctor(self._args(strict=True))
        self.assertEqual(ctx.exception.code, 1)

    def test_json_report_printed(self):
        out = io.StringIO()
        report = {"summary": {"ok": 1}}
        with mock.patch.object(verify, "doctor_report", return_value=report), \
                mock.patch.object(verify, "strict_exit_code", return_value=0), \
                redirect_stdout(out):
            verify._run_doctor(self._args(as_json=True))
        self.assertIn('"summary"', out.getvalue())


class EnvelopeTests(unittest.TestCase):
    def _args(self):
        return SimpleNamespace(json=True)

    def test_internal_error_envelope(self):
        out = io.StringIO()
        old_ws = getattr(verify, "WORKSPACE", None)
        verify.WORKSPACE = None
        try:
            with redirect_stdout(out), redirect_stderr(io.StringIO()), \
                    mock.patch.object(verify, "_output") as output, \
                    mock.patch.object(verify, "_save_failure_context"):
                with self.assertRaises(SystemExit) as ctx:
                    verify._fail_with_envelope(RuntimeError("boom"), self._args())
            self.assertEqual(ctx.exception.code, 1)
            payload = output.call_args[0][0]
            self.assertEqual(payload["status"], "internal_error")
            self.assertIn("boom", payload["error"])
        finally:
            verify.WORKSPACE = old_ws

    def test_keyboard_interrupt_reraises(self):
        old_ws = getattr(verify, "WORKSPACE", None)
        verify.WORKSPACE = None
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    mock.patch.object(verify, "_output"), \
                    mock.patch.object(verify, "_save_failure_context"):
                try:
                    raise KeyboardInterrupt()
                except KeyboardInterrupt as exc:
                    with self.assertRaises(KeyboardInterrupt):
                        verify._fail_with_envelope(exc, self._args())
        finally:
            verify.WORKSPACE = old_ws


class PrepareContextTests(unittest.TestCase):
    def test_no_project_exits_one(self):
        with mock.patch.object(verify, "find_project_root", return_value=None),                 redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                verify._prepare_context(SimpleNamespace(project=None))
        self.assertEqual(ctx.exception.code, 1)

    def test_bad_config_exits_one(self):
        with mock.patch.object(verify, "find_project_root", return_value="/ws"), \
                mock.patch.object(verify, "load_config", side_effect=verify.ConfigError("bad")),                 redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                verify._prepare_context(SimpleNamespace(project=None))
        self.assertEqual(ctx.exception.code, 1)

    def test_low_version_exits_one(self):
        config = {"toolkit_min_version": "99.0"}
        with mock.patch.object(verify, "find_project_root", return_value="/ws"), \
                mock.patch.object(verify, "load_config", return_value=config), \
                mock.patch.object(verify, "esp_backend_config_errors", return_value=[]), \
                mock.patch.object(verify, "load_expectations", return_value=None), \
                mock.patch.object(verify, "version_ok", return_value=False),                 redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                verify._prepare_context(SimpleNamespace(project=None))
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
