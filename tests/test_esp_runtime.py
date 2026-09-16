"""esp_runtime (F-174) — ESP32-S3 三后端的 host 单测, 零真机零 IO。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import esp_runtime


class RunIdfTests(unittest.TestCase):
    def _fake_run(self, rc=0, out="hello", err=""):
        seen = {}
        def fake(cmd, **kw):
            seen["cmd"] = cmd
            seen["kw"] = kw
            return SimpleNamespace(returncode=rc, stdout=out, stderr=err)
        return fake, seen

    def test_builds_powershell_with_export_and_gate(self):
        fake, seen = self._fake_run()
        with mock.patch.object(esp_runtime, "resolve_idf_path",
                               return_value=r"D:\idf\esp-idf"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            r = esp_runtime.run_idf(["idf.py build"], timeout=900,
                                    workspace=r"W:", _run=fake)
        self.assertEqual(r["status"], "ok")
        script = seen["cmd"][-1]                      # -Command 后的脚本文本
        self.assertIn(". 'D:/idf/esp-idf/export.ps1'", script)  # 正斜杠 (PS 不处理反斜杠转义)
        self.assertIn("idf.py build", script)
        self.assertIn("$LASTEXITCODE", script)         # 逐命令退出码门闩
        self.assertEqual(seen["cmd"][:3], ["powershell", "-NoProfile", "-ExecutionPolicy"])
        self.assertEqual(seen["kw"]["cwd"], "W:")

    def test_nonzero_rc_is_error_not_fail_open(self):
        # F-090 同源纪律: 输出里全是漂亮话, rc!=0 必须 error
        fake, _ = self._fake_run(rc=2, out="Hash of data verified")
        with mock.patch.object(esp_runtime, "resolve_idf_path", return_value="X"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            r = esp_runtime.run_idf(["idf.py flash"], 60, "W:", _run=fake)
        self.assertEqual(r["status"], "error")
        self.assertEqual(r["returncode"], 2)

    def test_timeout_returns_message(self):
        def boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="powershell", timeout=1)
        with mock.patch.object(esp_runtime, "resolve_idf_path", return_value="X"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            r = esp_runtime.run_idf(["x"], 1, "W:", _run=boom)
        self.assertEqual(r["status"], "error")
        self.assertIn("超时", r["message"])


    def test_export_path_single_quote_escaped(self):
        # Task 2 审查裁决: PS 单引号串内 ' 须翻倍转义, 防路径注入/断串
        fake, seen = self._fake_run()
        with mock.patch.object(esp_runtime, "resolve_idf_path",
                               return_value=r"D:\id'f\esp-idf"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            esp_runtime.run_idf(["idf.py build"], timeout=900,
                                workspace=r"W:", _run=fake)
        script = seen["cmd"][-1]
        self.assertIn("D:/id''f/esp-idf/export.ps1", script)


class ResolveIdfPathTests(unittest.TestCase):
    def test_missing_key_raises(self):
        with mock.patch.object(esp_runtime, "load_machine", return_value={}):
            with self.assertRaises(esp_runtime.EspConfigError):
                esp_runtime.resolve_idf_path()

    def test_nonexistent_dir_raises(self):
        with mock.patch.object(esp_runtime, "load_machine",
                               return_value={"esp_idf_path": r"Q:\nope"}):
            with self.assertRaises(esp_runtime.EspConfigError):
                esp_runtime.resolve_idf_path()

    def test_ok_path_returns_it(self):
        with mock.patch.object(esp_runtime, "load_machine",
                               return_value={"esp_idf_path": os.getcwd()}):
            self.assertEqual(esp_runtime.resolve_idf_path(), os.getcwd())


class PanicMarkerTests(unittest.TestCase):
    def test_markers(self):
        self.assertTrue(esp_runtime.detect_esp_panic("Guru Meditation Error: Core 0"))
        self.assertTrue(esp_runtime.detect_esp_panic("Backtrace: 0x4037abcd:0x3fc..."))
        self.assertTrue(esp_runtime.detect_esp_panic("abort() was called at PC ..."))
        self.assertFalse(esp_runtime.detect_esp_panic("ESP-PILOT-OK tick=1"))


class StepBuildIdfTests(unittest.TestCase):
    """mock run_idf + tmpdir 产物, 钉: 命令装配/日志落盘/metrics/state.json 契约。"""

    def _ws(self, td, with_artifacts=True):
        os.makedirs(os.path.join(td, "build"), exist_ok=True)
        os.makedirs(os.path.join(td, ".workbench"), exist_ok=True)
        if with_artifacts:
            open(os.path.join(td, "build", "esp32s3_hello.bin"), "w").close()
            open(os.path.join(td, "build", "esp32s3_hello.elf"), "w").close()
        return td

    def test_success_contract(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            r = esp_runtime.step_build_idf({"idf": {}}, workspace=ws,
                                           _run_idf=lambda c, **kw: {
                        "status": "ok", "returncode": 0,
                        "output": "Executing idf.py build\nDone\n"})
            self.assertEqual(r["status"], "ok")
            self.assertEqual(r["metrics"], {"errors": 0, "warnings": 0})
            self.assertEqual(r["details"]["hex_file"], "build/esp32s3_hello.bin")
            self.assertEqual(r["details"]["elf_file"], "build/esp32s3_hello.elf")
            self.assertTrue(os.path.isfile(os.path.join(
                ws, r["details"]["log_file"])))          # 日志落盘
            with open(os.path.join(ws, ".workbench", "state.json"),
                      encoding="utf-8") as f:
                lb = json.load(f)["last_build"]
            self.assertEqual(lb["provider"], "idf")
            self.assertEqual(lb["hex_file"], "build/esp32s3_hello.bin")  # verify --no-build 回读键

    def test_error_line_counted_and_status_error(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            r = esp_runtime.step_build_idf({}, workspace=ws, _run_idf=lambda c, **kw: {
                "status": "error", "returncode": 2,
                "output": "main.c:5:1: error: 'foo' undeclared\nninja: build stopped\n"})
            self.assertEqual(r["status"], "error")
            self.assertEqual(r["metrics"]["errors"], 1)

    def test_rc_zero_but_error_line_still_error(self):
        # rc=0 但日志含 error: → 不许按成功入账 (F-090 判据的补充证据方向)
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            r = esp_runtime.step_build_idf({}, workspace=ws, _run_idf=lambda c, **kw: {
                "status": "ok", "returncode": 0, "output": "cc1: error: bad\n"})
            self.assertEqual(r["status"], "error")

    def test_no_bin_artifact_errors(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td, with_artifacts=False)
            r = esp_runtime.step_build_idf({}, workspace=ws, _run_idf=lambda c, **kw: {
                "status": "ok", "returncode": 0, "output": "Done\n"})
            self.assertEqual(r["status"], "error")
            self.assertIn("bin", r["summary"].lower())

    def test_rebuild_prepends_fullclean(self):
        seen = []
        def spy(cmds, **kw):
            seen.append(list(cmds))
            return {"status": "ok", "returncode": 0, "output": "Done\n"}
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            esp_runtime.step_build_idf({}, rebuild=True, workspace=ws, _run_idf=spy)
        self.assertEqual(seen[0], ["idf.py fullclean", "idf.py build"])


if __name__ == "__main__":
    unittest.main()
