r"""F-245: verify 的构建/烧录派发、早退落账、信封现场写盘补测。

## 覆盖对象

`scripts/verify.py` 此前 88% 覆盖（2026-11-02 实测）：`step_build` 的
rebuild+keil 拒绝与 idf 派发、`step_flash` 的 esptool 派发与 openocd
目标解析失败、`_record_checkpoint_early_exit`、`_fail_fast_on_bad_patterns`
的非 ExpectationError 分支、`main` 的 doctor 分支、`_fail_with_envelope`
的现场写盘成功/失败两条路径。

## 夹具

模块引用替换 + 临时工程；不接硬件。
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


class StepBuildDispatchTests(unittest.TestCase):
    def test_rebuild_rejected_for_keil(self):
        result = verify.step_build({}, builder="keil", rebuild=True)
        self.assertEqual(result["status"], "error")
        self.assertIn("--rebuild", result["message"])

    def test_idf_dispatch(self):
        with mock.patch.object(verify, "esp_runtime") as esp:
            esp.step_build_idf.return_value = {"status": "ok"}
            result = verify.step_build({"x": 1}, builder="idf", rebuild=True)
        self.assertEqual(result["status"], "ok")
        esp.step_build_idf.assert_called_once()


class StepFlashDispatchTests(unittest.TestCase):
    def test_missing_hex(self):
        result = verify.step_flash("")
        self.assertEqual(result["status"], "error")

    def test_esptool_dispatch(self):
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "fw.bin"), "w", encoding="utf-8") as fh:
                fh.write("x")
            old = getattr(verify, "WORKSPACE", None)
            verify.WORKSPACE = ws
            try:
                with mock.patch.object(verify, "esp_runtime") as esp:
                    esp.step_flash_esptool.return_value = {"status": "ok"}
                    result = verify.step_flash("fw.bin", {"flash": {"backend": "esptool"}})
            finally:
                verify.WORKSPACE = old
        self.assertEqual(result["status"], "ok")

    def test_openocd_target_error(self):
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "fw.hex"), "w", encoding="utf-8") as fh:
                fh.write(":00000001FF\n")
            old = getattr(verify, "WORKSPACE", None)
            verify.WORKSPACE = ws
            try:
                with mock.patch.object(verify, "_openocd_target",
                                       side_effect=verify.OpenocdCfgError("bad target")):
                    result = verify.step_flash("fw.hex", {})
            finally:
                verify.WORKSPACE = old
        self.assertEqual(result["status"], "error")
        self.assertIn("bad target", result["message"])


class EarlyCheckpointTests(unittest.TestCase):
    def test_no_workspace_is_noop(self):
        old = getattr(verify, "WORKSPACE", None)
        verify.WORKSPACE = None
        try:
            verify._record_checkpoint_early_exit({}, SimpleNamespace())
        finally:
            verify.WORKSPACE = old

    def test_with_workspace_records(self):
        old = getattr(verify, "WORKSPACE", None)
        verify.WORKSPACE = "/ws"
        try:
            with mock.patch.object(verify, "record_checkpoint") as rec:
                verify._record_checkpoint_early_exit(
                    {"status": "error", "steps": {}, "elapsed_sec": 1.0},
                    SimpleNamespace(task_origin="manual", gate_run=False))
        finally:
            verify.WORKSPACE = old
        rec.assert_called_once()


class FailFastGenericTests(unittest.TestCase):
    def test_unexpected_exception_becomes_bad_pattern(self):
        with mock.patch.object(verify, "load_expectations",
                               side_effect=RuntimeError("corrupt")):
            with self.assertRaises(verify.BadPatternError) as ctx:
                verify._fail_fast_on_bad_patterns({})
        self.assertIn("不可读", str(ctx.exception))


class MainDoctorTests(unittest.TestCase):
    def test_doctor_branch_returns(self):
        with mock.patch.object(verify, "_parse_args",
                               return_value=SimpleNamespace(
                                   doctor=True, junit_xml=None)), \
                mock.patch.object(verify, "_run_doctor") as doc:
            verify.main()
        doc.assert_called_once()


class EnvelopeContextTests(unittest.TestCase):
    def _args(self):
        return SimpleNamespace(json=True)

    def test_context_path_recorded_when_file_written(self):
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, ".workbench"))
            with open(os.path.join(ws, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            old = getattr(verify, "WORKSPACE", None)
            verify.WORKSPACE = ws

            def _save(result, **_kw):
                path = os.path.join(ws, ".workbench", "build", "last_failure.json")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("{}")

            try:
                with mock.patch.object(verify, "_save_failure_context", side_effect=_save), \
                        mock.patch.object(verify, "_output") as output, \
                        redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        verify._fail_with_envelope(RuntimeError("boom"), self._args())
            finally:
                verify.WORKSPACE = old
        payload = output.call_args[0][0]
        self.assertIn("failure_context_path", payload)

    def test_write_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, ".workbench"))
            with open(os.path.join(ws, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            old = getattr(verify, "WORKSPACE", None)
            verify.WORKSPACE = ws
            try:
                with mock.patch.object(verify, "_save_failure_context"), \
                        mock.patch.object(verify, "_output") as output, \
                        redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        verify._fail_with_envelope(RuntimeError("boom"), self._args())
            finally:
                verify.WORKSPACE = old
        payload = output.call_args[0][0]
        self.assertTrue(payload["failure_context_write_failed"])


if __name__ == "__main__":
    unittest.main()
