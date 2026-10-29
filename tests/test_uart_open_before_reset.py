"""F-235: open_before_reset —— 先开串口再复位, 防 CDC 设备丢首行。

WCH-Link 属 CDC 类, Windows 在句柄打开前不缓存; 复位早于开串口
⇒ banner 必丢 (试点 Critical 1+2 的原症状)。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import esp_runtime  # noqa: E402


class _FakeSerial:
    """记录 open/close 顺序与 readline 返回值。"""

    events = []

    def __init__(self, *a, **kw):
        _FakeSerial.events.append("open")
        self._lines = [b"=== boot ===\r\n"]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        _FakeSerial.events.append("close")
        return False

    @property
    def dtr(self):
        return False

    @dtr.setter
    def dtr(self, v):
        pass

    @property
    def rts(self):
        return False

    @rts.setter
    def rts(self, v):
        pass

    def readline(self):
        return self._lines.pop(0) if self._lines else b""

    def close(self):
        _FakeSerial.events.append("close")


class OpenBeforeResetTests(unittest.TestCase):
    def setUp(self):
        _FakeSerial.events = []
        self.serial_mod = mock.Mock()
        self.serial_mod.Serial = _FakeSerial
        self.serial_mod.SerialException = OSError

    def _run(self, open_first, reset_mode="none"):
        reset_calls = []

        def fake_reset(exe, cfg=None, timeout=20):
            reset_calls.append(("reset", list(_FakeSerial.events)))
            return {"status": "ok"}

        cfg = {"port": "COM15", "baudrate": 115200, "settle_sec": 0,
               "reset": reset_mode, "open_before_reset": open_first}
        with mock.patch.dict(sys.modules, {"serial": self.serial_mod}), \
             mock.patch.object(esp_runtime, "load_machine",
                               return_value={"openocd_exe": "/oc"}), \
             mock.patch("openocd_runtime.reset_target", fake_reset):
            esp_runtime.step_capture_uart(0.1, cfg, workspace=".")
        return _FakeSerial.events, reset_calls

    def test_open_before_reset_true_opens_port_first(self):
        events, resets = self._run(True, reset_mode="openocd")
        self.assertEqual(events[0], "open")
        self.assertEqual(resets[0][1][0], "open")   # 复位发生时口已开

    def test_default_false_keeps_legacy_order(self):
        events, resets = self._run(False, reset_mode="openocd")
        self.assertNotIn("open", resets[0][1])      # 复位时口未开
        self.assertIn("open", events)

    def test_non_bool_rejected(self):
        cfg = {"port": "COM15", "open_before_reset": "yes"}
        got = esp_runtime.step_capture_uart(0.1, cfg, workspace=".")
        self.assertEqual(got["status"], "error")
        self.assertIn("open_before_reset", got["error"])

    def test_esptool_reset_rejected_as_mutually_exclusive(self):
        """esptool 复位要独占串口, 与"先开口"不可兼得 —— 配置期即拒,
        不许拖到复位现场报"复位失败 (端口被占…)" 把用户引去查板子。"""
        cfg = {"port": "COM15", "settle_sec": 0, "reset": "esptool",
               "open_before_reset": True}
        with mock.patch.dict(sys.modules, {"serial": self.serial_mod}):
            got = esp_runtime.step_capture_uart(
                0.1, cfg, workspace=".",
                _run_idf=lambda c, **kw: {"status": "ok", "output": ""})
        self.assertEqual(got["status"], "error")
        self.assertEqual(got["method"], "uart")
        self.assertIn("capture.open_before_reset", got["error"])
        self.assertIn("capture.reset", got["error"])
        self.assertNotIn("复位失败", got["error"])

    def test_open_failure_reports_readable_error(self):
        """先开口分支的打开失败自己出可读错, 不落到"复位失败"外套里。"""
        def boom(*a, **kw):
            raise OSError("Access denied")
        self.serial_mod.Serial = boom
        cfg = {"port": "COM15", "settle_sec": 0, "reset": "none",
               "open_before_reset": True}
        with mock.patch.dict(sys.modules, {"serial": self.serial_mod}):
            got = esp_runtime.step_capture_uart(0.1, cfg, workspace=".")
        self.assertEqual(got["status"], "error")
        self.assertIn("串口打开失败", got["error"])
        self.assertIn("COM15", got["error"])

    def test_reset_failure_closes_handle_first(self):
        """复位失败必须先关回已开句柄 (Windows 独占口, 泄漏会卡死重试)。"""
        def bad_reset(exe, cfg=None, timeout=20):
            return {"status": "error", "message": "SWD 无响应"}
        cfg = {"port": "COM15", "settle_sec": 0, "reset": "openocd",
               "open_before_reset": True}
        with mock.patch.dict(sys.modules, {"serial": self.serial_mod}), \
             mock.patch.object(esp_runtime, "load_machine",
                               return_value={"openocd_exe": "/oc"}), \
             mock.patch("openocd_runtime.reset_target", bad_reset):
            got = esp_runtime.step_capture_uart(0.1, cfg, workspace=".")
        self.assertEqual(got["status"], "error")
        self.assertIn("复位失败", got["error"])
        self.assertEqual(_FakeSerial.events, ["open", "close"])


class WchResetDispatchTests(unittest.TestCase):
    """F-235: capture.reset=openocd 的复位目标随工程 gcc.toolchain 分流。

    修前恒取 machine.openocd_exe 且 cfg=None (reset_target 内部的 arm
    默认链) —— 对 CH32V307 (RISC-V) 目标, 那是拿 ST-Link 的 openocd 与
    stm32f1x.cfg 去连 wch_riscv 核, 必失败。arm 的调用形态按既有裁决
   保持不变 (exe + cfg=None)。
    """

    MACHINE = {"openocd_exe": "/arm/openocd",
               "wch_openocd_exe": "/wch/openocd",
               "wch_openocd_cfg": "/wch/wch-riscv.cfg"}

    def setUp(self):
        self.serial_mod = mock.Mock()
        self.serial_mod.Serial = _FakeSerial
        self.serial_mod.SerialException = OSError
        _FakeSerial.events = []

    def _ws(self, gcc_section=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, ".workbench"))
        with open(os.path.join(d, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"gcc": gcc_section or {}}, f)
        return d

    def _run(self, workspace, machine=None):
        calls = []

        def fake_reset(exe, cfg=None, timeout=20):
            calls.append((exe, cfg))
            return {"status": "ok"}

        cfg = {"port": "COM15", "baudrate": 115200, "settle_sec": 0,
               "reset": "openocd", "open_before_reset": True}
        with mock.patch.dict(sys.modules, {"serial": self.serial_mod}), \
             mock.patch.object(esp_runtime, "load_machine",
                               return_value=machine or self.MACHINE), \
             mock.patch("openocd_runtime.reset_target", fake_reset):
            got = esp_runtime.step_capture_uart(0.1, cfg, workspace=workspace)
        return got, calls

    def test_wch_workspace_resets_with_wch_target(self):
        got, calls = self._run(self._ws({"toolchain": "wch"}))
        self.assertEqual(got["status"], "ok")
        self.assertEqual(calls, [("/wch/openocd", ["/wch/wch-riscv.cfg"])])

    def test_arm_workspace_keeps_legacy_call(self):
        got, calls = self._run(self._ws())
        self.assertEqual(got["status"], "ok")
        self.assertEqual(calls, [("/arm/openocd", None)])

    def test_wch_missing_keys_reports_readable_error(self):
        """wch 缺键 → 复位失败的可读报错 (点名键名), 不是裸 KeyError。"""
        got, calls = self._run(
            self._ws({"toolchain": "wch"}),
            machine={"openocd_exe": "/arm/openocd",
                     "wch_openocd_cfg": "/wch/wch-riscv.cfg"})
        self.assertEqual(calls, [])
        self.assertEqual(got["status"], "error")
        self.assertIn("复位失败", got["error"])
        self.assertIn("wch_openocd_exe", got["error"])


if __name__ == "__main__":
    unittest.main()
