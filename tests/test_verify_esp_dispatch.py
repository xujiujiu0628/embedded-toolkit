"""verify.py F-174 派发钉 — 新分支被正确路由 + 缺省路径回归 (builder/flash/capture 三处)。"""
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


if __name__ == "__main__":
    unittest.main()
