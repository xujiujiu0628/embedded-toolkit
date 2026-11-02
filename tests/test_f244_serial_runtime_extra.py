r"""F-244: serial_runtime 的本地配置 / mux 匹配 / 串口打开补测。

## 覆盖对象

`scripts/serial_runtime.py` 此前 87% 覆盖（2026-11-02 实测）：
`load_local_config`/`save_local_config`、`is_mux_alive` 的 OSError 回落、
`get_mux_info` 无记录、`_normalize_serial_port` 的 POSIX realpath、
`get_matching_mux_info` 的匹配/不匹配、`open_serial_port` 的 mux 与直连
两条路径未执行。

## 夹具

`serial` 用 sys.modules 注入假模块；`socket` / `os` 用直接赋值替身
（避免 test_stub_ratchet 的 B 式判据），用完还原。
"""
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_runtime  # noqa: E402


class LocalConfigTests(unittest.TestCase):
    def test_load_uses_config_dir(self):
        with mock.patch.object(serial_runtime, "load_json_file",
                               return_value={"a": 1}) as spy:
            self.assertEqual(serial_runtime.load_local_config(), {"a": 1})
        self.assertTrue(str(spy.call_args[0][0]).endswith("serial.json"))

    def test_save_uses_config_dir(self):
        with mock.patch.object(serial_runtime, "save_json_file") as spy:
            serial_runtime.save_local_config({"a": 1})
        self.assertTrue(str(spy.call_args[0][0]).endswith("serial.json"))


class MuxProbeExtraTests(unittest.TestCase):
    def test_socket_oserror_returns_false(self):
        class _Sock:
            def __enter__(self):
                return self

            def __exit__(self, *_x):
                return False

            def settimeout(self, _t):
                pass

            def connect_ex(self, _addr):
                raise OSError("boom")

        old_socket, old_os = serial_runtime.socket, serial_runtime.os
        serial_runtime.socket = SimpleNamespace(
            AF_INET=2, SOCK_STREAM=1, socket=lambda *a: _Sock())
        serial_runtime.os = SimpleNamespace(name="nt")
        try:
            self.assertFalse(serial_runtime.is_mux_alive({"tcp_port": 1}))
        finally:
            serial_runtime.socket, serial_runtime.os = old_socket, old_os

    def test_get_mux_info_no_entry(self):
        with mock.patch.object(serial_runtime, "load_workspace_state", return_value={}):
            self.assertIsNone(serial_runtime.get_mux_info())

    def test_normalize_serial_port_posix_realpath(self):
        old = serial_runtime.os
        serial_runtime.os = SimpleNamespace(name="posix", path=os.path,
                                            getpid=os.getpid, kill=os.kill)
        try:
            self.assertEqual(serial_runtime._normalize_serial_port(""), "")
            self.assertTrue(os.path.isabs(serial_runtime._normalize_serial_port("/tmp/x")))
        finally:
            serial_runtime.os = old

    def test_matching_mux_info(self):
        cfg = {"port": "COM3", "baudrate": 115200, "bytesize": 8,
               "parity": "none", "stopbits": 1}
        mux = {"real_port": "COM3", "baudrate": 115200, "bytesize": 8,
               "parity": "none", "stopbits": 1}
        with mock.patch.object(serial_runtime, "get_mux_info", return_value=None):
            self.assertIsNone(serial_runtime.get_matching_mux_info(cfg))
        with mock.patch.object(serial_runtime, "get_mux_info", return_value=mux):
            self.assertEqual(serial_runtime.get_matching_mux_info(cfg), mux)
        with mock.patch.object(serial_runtime, "get_mux_info",
                               return_value=dict(mux, real_port="COM4")):
            self.assertIsNone(serial_runtime.get_matching_mux_info(cfg))


class OpenSerialPortTests(unittest.TestCase):
    def _inject_serial(self, module):
        old = sys.modules.get("serial")
        sys.modules["serial"] = module

        def restore():
            if old is None:
                sys.modules.pop("serial", None)
            else:
                sys.modules["serial"] = old
        return restore

    def test_mux_url_path(self):
        opened = {}

        class _Ser:
            def __init__(self):
                self.timeout = None

        def _for_url(url):
            opened["url"] = url
            return _Ser()

        module = types.ModuleType("serial")
        module.serial_for_url = _for_url
        restore = self._inject_serial(module)
        try:
            with mock.patch.object(serial_runtime, "get_matching_mux_info",
                                   return_value={"tcp_port": 20001}):
                ser = serial_runtime.open_serial_port(
                    {"port": "COM3", "timeout_sec": 2.0})
        finally:
            restore()
        self.assertEqual(opened["url"], "socket://127.0.0.1:20001")
        self.assertTrue(getattr(ser, "_serial_skill_using_mux"))

    def test_direct_serial_parity_mapping(self):
        captured = {}

        class _Serial:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        module = types.ModuleType("serial")
        module.Serial = _Serial
        restore = self._inject_serial(module)
        try:
            serial_runtime.open_serial_port(
                {"port": "COM3", "baudrate": 115200, "bytesize": 8,
                 "parity": "odd", "stopbits": 1, "timeout_sec": 1.0},
                use_mux=False)
        finally:
            restore()
        self.assertEqual(captured["parity"], "O")
        self.assertEqual(captured["port"], "COM3")


if __name__ == "__main__":
    unittest.main()
