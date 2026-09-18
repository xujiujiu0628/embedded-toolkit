"""verify.py F-174 派发钉 — 新分支被正确路由 + 缺省路径回归 (builder/flash/capture 三处)。"""
import argparse
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import esp_runtime  # noqa: E402
import openocd_run  # noqa: E402
import verify  # noqa: E402


class StepBuildDispatchTests(unittest.TestCase):
    def test_idf_routes_to_esp_runtime(self):
        with mock.patch.object(esp_runtime, "step_build_idf",
                               return_value={"status": "ok"}) as m:
            r = verify.step_build({"builder": "idf"}, builder="idf",
                                  rebuild=True)
        m.assert_called_once()                       # rebuild 旗标也放行到 idf (fullclean)
        self.assertEqual(r["status"], "ok")

    def test_gcc_default_untouched(self):
        # 缺省回归钉: gcc 路径仍走 run_py(GCC_BUILD)
        with mock.patch.object(verify, "run_py",
                               return_value={"status": "ok"}) as m:
            verify.step_build({"gcc": {"project": "p/Makefile"}}, builder="gcc")
        self.assertIn("gcc_build.py", m.call_args[0][0])

    def test_analyze_idf_passthrough_metrics(self):
        r = verify.step_analyze("x.log", builder="idf",
                                build_metrics={"errors": 0, "warnings": 3})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["summary"]["warnings"], 3)


class StepFlashDispatchTests(unittest.TestCase):
    """step_flash 新签名 (artifact, config=None): 缺省 openocd, esptool 路由。"""

    def _mk_artifact(self, td):
        rel = os.path.join("build", "app.bin")
        os.makedirs(os.path.dirname(os.path.join(td, rel)), exist_ok=True)
        open(os.path.join(td, rel), "w").close()
        return rel

    def test_esptool_routes_to_esp_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            rel = self._mk_artifact(td)
            with mock.patch.object(verify, "WORKSPACE", td), \
                 mock.patch.object(esp_runtime, "step_flash_esptool",
                                   return_value={"status": "ok"}) as m:
                r = verify.step_flash(rel, {"flash": {"backend": "esptool",
                                                      "port": "COM3"}})
            self.assertEqual(r["status"], "ok")
            self.assertEqual(m.call_args[0][0], {"backend": "esptool",
                                                 "port": "COM3"})

    def test_default_config_openocd_untouched(self):
        # 缺省回归钉: config=None 与 config={} 都必须走今天的 OpenOCD 命令
        # (桩返回真标记串: rc=0 时 OpenOCD 分支过 marker_present 检查, F-163)
        with tempfile.TemporaryDirectory() as td:
            rel = self._mk_artifact(td)
            with mock.patch.object(verify, "WORKSPACE", td), \
                 mock.patch.object(verify, "_openocd_exe", return_value="ocd.exe"), \
                 mock.patch.object(verify, "run_cmd",
                                   return_value={"status": "ok", "returncode": 0,
                                                 "stdout": openocd_run.ACTION_DONE_MARKER + "\n",
                                                 "stderr": ""}) as m:
                for cfg in (None, {}):
                    r = verify.step_flash(rel, cfg)
                    self.assertEqual(r["status"], "ok")
            cmd = m.call_args[0][0]
            self.assertEqual(cmd[0], "ocd.exe")
            self.assertIn("interface/stlink.cfg", cmd)   # STM32 串逐字节不变
            # 诚实断言: 桩返回值确实携带 F-163 构造性标记
            self.assertTrue(verify.marker_present(
                m.return_value["stdout"] + m.return_value["stderr"]))


class CaptureUartDispatchTests(unittest.TestCase):
    def _args(self):
        return argparse.Namespace(timeout=5, task_origin="manual",
                                  require_schedule_origin=False, json=True)

    def test_uart_branch_writes_capture_step_and_panic(self):
        cfg = {"capture": {"backend": "uart", "port": "COM9"},
               "verify": {"expect": ["ESP-PILOT-OK"]}}
        result = {"steps": {}}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(verify, "WORKSPACE", td), \
             mock.patch.object(esp_runtime, "step_capture_uart",
                     return_value={"status": "ok", "method": "uart",
                                   "esp_panic": True,
                                   "_text": "Guru Meditation Error"}) as m, \
             mock.patch.object(verify, "append_audit_entry"):
            text, lines, tmo = verify._run_capture_step(
                self._args(), cfg, result, None, False, "uart", {}, 0, "")
        self.assertIn("Guru", text)
        self.assertEqual(result["steps"]["capture"]["method"], "uart")
        self.assertTrue(result["steps"]["capture"]["esp_panic"])
        self.assertTrue(result.get("esp_panic"))   # 顶层标记供 judge
        self.assertEqual(tmo, 5)
        m.assert_called_once()

    def test_uart_failure_early_exit(self):
        cfg = {"capture": {"backend": "uart", "port": "COM9"}, "verify": {}}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(verify, "WORKSPACE", td), \
             mock.patch.object(esp_runtime, "step_capture_uart",
                     return_value={"status": "error", "method": "uart",
                                   "error": "串口 COM9 采集失败"}), \
             mock.patch.object(verify, "append_audit_entry"), \
             mock.patch.object(verify, "_save_failure_context"), \
             mock.patch.object(verify, "_output"), \
             mock.patch.object(verify, "_record_checkpoint_early_exit"):
            with self.assertRaises(SystemExit) as cm:
                verify._run_capture_step(
                    self._args(), cfg, {"steps": {}}, None, False, "uart", {}, 0, "")
        self.assertEqual(cm.exception.code, 1)     # 失败早退非零纪律

    def test_default_backend_still_semihosting(self):
        # 缺省回归钉: cap_backend 默认值路径不碰 esp_runtime
        cfg = {"capture": {"backend": "semihosting"}, "verify": {}}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(verify, "WORKSPACE", td), \
             mock.patch.object(verify, "run_semihosting_session",
                     return_value=("", "")) as m, \
             mock.patch.object(verify, "append_audit_entry"):
            verify._run_capture_step(self._args(), cfg, {"steps": {}},
                                     None, False, "semihosting", {}, 0, "")
        m.assert_called_once()


if __name__ == "__main__":
    unittest.main()
