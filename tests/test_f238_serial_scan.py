r"""F-238: serial_scan 的芯片映射与 CLI 输出补测。

## 覆盖对象

`scripts/serial_scan.py` 此前 42% 覆盖（2026-11-02 实测）：`main()` 的
空列表 / 非空列表 / Mux 运行中 / 错误出口，以及 `load_chip_map` 的异常
回落从未执行。

## 夹具

`scan_serial_ports` / `get_mux_info` 模块引用替换，不枚举真实端口。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_scan  # noqa: E402


def _run_main(argv, ports, err="", mux=None):
    out = io.StringIO()
    err_stream = io.StringIO()
    old_argv = sys.argv
    sys.argv = ["serial_scan.py", *argv]
    try:
        with mock.patch.object(serial_scan, "scan_serial_ports", return_value=(ports, err)), \
                mock.patch.object(serial_scan, "get_mux_info", return_value=mux), \
                redirect_stdout(out), redirect_stderr(err_stream):
            try:
                rc = serial_scan.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old_argv
    return rc, out.getvalue()


PORT = {
    "port": "COM3", "description": "USB Serial", "chip": "CH340",
    "vid": "1A86", "pid": "7523",
}


class ChipMapTests(unittest.TestCase):
    def test_real_data_loads_chip_entries(self):
        chip_map = serial_scan.load_chip_map()
        self.assertIn(("1A86", "7523"), chip_map)
        self.assertEqual(chip_map[("1A86", "7523")], "CH340")

    def test_missing_file_returns_empty_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(serial_scan, "COMMON_DEVICES_PATH",
                                   Path(tmp) / "nope.json"):
                self.assertEqual(serial_scan.load_chip_map(), {})

    def test_corrupt_file_returns_empty_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with mock.patch.object(serial_scan, "COMMON_DEVICES_PATH", path):
                self.assertEqual(serial_scan.load_chip_map(), {})


class ScanPortsTests(unittest.TestCase):
    def test_delegates_to_runtime_scanner(self):
        with mock.patch.object(serial_scan, "scan_serial_ports",
                               return_value=([PORT], "")) as spy:
            ports, err = serial_scan.scan_ports("CH340")
        spy.assert_called_once_with("CH340")
        self.assertEqual(ports, [PORT])
        self.assertEqual(err, "")


class MainTests(unittest.TestCase):
    def test_text_output_lists_ports(self):
        rc, out = _run_main([], [PORT])
        self.assertIsNone(rc)
        self.assertIn("发现 1 个串口", out)
        self.assertIn("COM3", out)
        self.assertIn("[CH340]", out)
        self.assertIn("VID:1A86", out)

    def test_empty_list(self):
        rc, out = _run_main([], [])
        self.assertIsNone(rc)
        self.assertIn("未发现可用串口", out)

    def test_json_output(self):
        rc, out = _run_main(["--json"], [PORT])
        self.assertIsNone(rc)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["details"]["ports"], [PORT])

    def test_mux_info_appended(self):
        mux = {"vserial": "COM10", "tcp_port": 5555, "real_port": "COM3"}
        rc, out = _run_main([], [PORT], mux=mux)
        self.assertIsNone(rc)
        self.assertIn("Mux 运行中", out)
        self.assertIn("COM10", out)

    def test_scan_error_exits_one(self):
        rc, out = _run_main([], [], err="pyserial 未安装")
        self.assertEqual(rc, 1)

    def test_scan_error_json(self):
        rc, out = _run_main(["--json"], [], err="pyserial 未安装")
        self.assertEqual(rc, 1)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "import_error")


if __name__ == "__main__":
    unittest.main()
