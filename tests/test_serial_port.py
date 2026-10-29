"""F-235: capture.port 的 auto:<描述子串> 端口发现。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_port  # noqa: E402


def _port(device, description="", hwid=""):
    p = mock.Mock()
    p.device, p.description, p.hwid = device, description, hwid
    return p


class ResolvePortTests(unittest.TestCase):
    def test_literal_passthrough(self):
        self.assertEqual(serial_port.resolve_port("COM15"), {"port": "COM15"})

    def test_empty_config_is_error(self):
        self.assertIn("error", serial_port.resolve_port(""))

    def test_auto_single_match(self):
        ports = [_port("COM5", "蓝牙链接上的标准串行"),
                 _port("COM15", "WCH-Link SERIAL")]
        with mock.patch.object(serial_port.list_ports, "comports", return_value=ports):
            self.assertEqual(serial_port.resolve_port("auto:WCH-Link SERIAL"),
                             {"port": "COM15"})

    def test_auto_is_case_insensitive(self):
        ports = [_port("COM15", "WCH-Link SERIAL")]
        with mock.patch.object(serial_port.list_ports, "comports", return_value=ports):
            self.assertEqual(serial_port.resolve_port("auto:wch-link serial"),
                             {"port": "COM15"})

    def test_auto_no_match_lists_ports(self):
        ports = [_port("COM5", "蓝牙")]
        with mock.patch.object(serial_port.list_ports, "comports", return_value=ports):
            got = serial_port.resolve_port("auto:WCH-Link SERIAL")
        self.assertIn("error", got)
        self.assertIn("COM5", got["error"])

    def test_auto_multiple_match_refuses_to_guess(self):
        ports = [_port("COM15", "WCH-Link SERIAL"), _port("COM16", "WCH-Link SERIAL")]
        with mock.patch.object(serial_port.list_ports, "comports", return_value=ports):
            got = serial_port.resolve_port("auto:WCH-Link SERIAL")
        self.assertIn("error", got)
        self.assertIn("多个", got["error"])

    def test_auto_without_needle(self):
        self.assertIn("error", serial_port.resolve_port("auto:"))

    def test_matches_hwid_too(self):
        ports = [_port("COM9", "", "USB VID:PID=1A86:8010 SER=WCH-Link")]
        with mock.patch.object(serial_port.list_ports, "comports", return_value=ports):
            self.assertEqual(serial_port.resolve_port("auto:1a86:8010"), {"port": "COM9"})


class MissingPyserialTests(unittest.TestCase):
    """宿主无 pyserial: 本模块仍可 import (esp_runtime 被 verify 顶层引用),
    字面量照用, 只有 auto: 报可读缺依赖错。"""

    def test_literal_still_works_without_pyserial(self):
        with mock.patch.object(serial_port, "list_ports", None):
            self.assertEqual(serial_port.resolve_port("COM15"), {"port": "COM15"})

    def test_auto_reports_missing_pyserial(self):
        with mock.patch.object(serial_port, "list_ports", None):
            got = serial_port.resolve_port("auto:WCH-Link SERIAL")
        self.assertIn("error", got)
        self.assertIn("pyserial", got["error"])


class ImportWithoutPyserialTests(unittest.TestCase):
    """偏差 A 的 import 期契约 (复审 Finding 2): 无 pyserial 宿主上
    `import serial_port` 本身不得抛 —— verify 顶层 import esp_runtime,
    退化成裸 `from serial.tools import list_ports` 时这条链直接崩, 而
    MissingPyserialTests 只造运行时态 (import 之后再置 None), 钉不住 import 期。"""

    POISONED = {"serial": None, "serial.tools": None,
                "serial.tools.list_ports": None}

    def test_import_and_auto_path_survive_without_pyserial(self):
        import importlib
        try:
            with mock.patch.dict(sys.modules, self.POISONED):
                importlib.reload(serial_port)       # 模拟首次 import 的模块体执行
                self.assertIsNone(serial_port.list_ports)
                self.assertEqual(serial_port.resolve_port("COM15"),
                                 {"port": "COM15"})
                got = serial_port.resolve_port("auto:WCH-Link SERIAL")
                self.assertIn("pyserial", got["error"])
        finally:
            importlib.reload(serial_port)           # 还原真模块, 不污染后续用例
        self.assertIsNotNone(serial_port.list_ports)


if __name__ == "__main__":
    unittest.main()
