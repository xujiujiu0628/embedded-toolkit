"""esp_runtime (F-174) — ESP32-S3 三后端的 host 单测, 零真机零 IO。"""
import os
import subprocess
import sys
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


if __name__ == "__main__":
    unittest.main()
