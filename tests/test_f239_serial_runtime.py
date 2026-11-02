r"""F-239: serial_runtime 的配置解析 / 连接骨架 / mux 探测补测。

## 覆盖对象

`scripts/serial_runtime.py` 此前 64% 覆盖（2026-11-02 实测）：`get_serial_config`
的优先级与自动扫描、`resolve_serial_config` / `connect_serial` 两条公共骨架、
`is_mux_alive` / `get_mux_info` / `config_matches_mux`、`scan_serial_ports`
的成功路径未执行。

## 夹具

- `serial` / `serial.tools.list_ports` 用 sys.modules 注入假模块（导入发生在
  函数内），用完还原；
- socket / os 用直接赋值替身（避免 test_stub_ratchet 的 B 式全局打桩判据）；
- state 读写用模块引用替换。
"""
import io
import os
import sys
import types
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_runtime  # noqa: E402


class _Port:
    def __init__(self, device="COM3", vid=0x1A86, pid=0x7523):
        self.device = device
        self.description = "USB Serial"
        self.vid = vid
        self.pid = pid
        self.serial_number = "SN"
        self.location = "1-1"


def _inject_serial(ports):
    module = types.ModuleType("serial.tools.list_ports")
    module.comports = lambda: list(ports)
    saved = {name: sys.modules.get(name) for name in
             ("serial", "serial.tools", "serial.tools.list_ports")}
    sys.modules["serial"] = types.ModuleType("serial")
    sys.modules["serial.tools"] = types.ModuleType("serial.tools")
    sys.modules["serial.tools.list_ports"] = module

    def restore():
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    return restore


class ScanPortsTests(unittest.TestCase):
    def test_success_maps_chip_and_filter(self):
        restore = _inject_serial([_Port("COM3"), _Port("COM4", vid=None, pid=None)])
        try:
            ports, err = serial_runtime.scan_serial_ports()
        finally:
            restore()
        self.assertIsNone(err)
        self.assertEqual([p["port"] for p in ports], ["COM3", "COM4"])
        self.assertEqual(ports[0]["chip"], "CH340")
        self.assertEqual(ports[1]["chip"], "")

    def test_filter_keyword(self):
        restore = _inject_serial([_Port("COM3"), _Port("COM4")])
        try:
            ports, _ = serial_runtime.scan_serial_ports("COM4")
        finally:
            restore()
        self.assertEqual([p["port"] for p in ports], ["COM4"])


class GetSerialConfigTests(unittest.TestCase):
    def _cfg(self, cli_port="COM3", project=None, state=None, ports=None, err=None):
        calls = []
        with mock.patch.object(serial_runtime, "load_project_config", return_value=project or {}), \
                mock.patch.object(serial_runtime, "load_workspace_state", return_value=state or {}), \
                mock.patch.object(serial_runtime, "scan_serial_ports",
                                  return_value=(ports or [], err)), \
                mock.patch.object(serial_runtime, "save_project_config",
                                  side_effect=lambda *a, **k: calls.append(a)):
            cfg, sources = serial_runtime.get_serial_config(cli_port=cli_port)
        return cfg, sources, calls

    def test_cli_port_with_defaults(self):
        cfg, sources, _ = self._cfg()
        self.assertEqual(cfg["port"], "COM3")
        self.assertEqual(cfg["baudrate"], 115200)
        self.assertEqual(cfg["parity"], "none")
        self.assertEqual(sources["port"], "cli")

    def test_project_config_overrides_defaults(self):
        cfg, sources, _ = self._cfg(
            cli_port="COM3", project={"baudrate": 9600, "parity": "even"})
        self.assertEqual(cfg["baudrate"], 9600)
        self.assertEqual(sources["baudrate"], "project:baudrate")

    def test_single_scan_autoselects_and_saves(self):
        cfg, sources, calls = self._cfg(cli_port=None, ports=[{"port": "COM9"}])
        self.assertEqual(cfg["port"], "COM9")
        self.assertEqual(sources["port"], "auto_scan")
        self.assertEqual(calls[0][1]["port"], "COM9")

    def test_multiple_ports_need_selection(self):
        cfg, sources, _ = self._cfg(cli_port=None, ports=[{"port": "COM1"}, {"port": "COM2"}])
        self.assertIsNone(cfg)
        self.assertTrue(sources["need_selection"])

    def test_no_ports_reports_error(self):
        cfg, sources, _ = self._cfg(cli_port=None, ports=[])
        self.assertIsNone(cfg)
        self.assertIn("未找到可用串口", sources["error"])

    def test_scan_error_propagates(self):
        cfg, sources, _ = self._cfg(cli_port=None, err="pyserial 未安装")
        self.assertIsNone(cfg)
        self.assertEqual(sources["error"], "pyserial 未安装")


class ResolveConfigTests(unittest.TestCase):
    def _args(self, **kw):
        base = dict(port="COM3", baudrate=None, bytesize=None, parity=None,
                    stopbits=None, encoding=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_success_saves_config(self):
        cfg = {"port": "COM3", "baudrate": 115200, "bytesize": 8,
               "parity": "none", "stopbits": 1, "encoding": "utf-8"}
        saved = []
        with mock.patch.object(serial_runtime, "get_serial_config",
                               return_value=(cfg, {"port": "cli"})), \
                mock.patch.object(serial_runtime, "save_project_config",
                                  side_effect=lambda *a, **k: saved.append(k)):
            out = serial_runtime.resolve_serial_config(self._args(), fail=lambda c, m: None)
        self.assertEqual(out, cfg)
        self.assertEqual(saved[0]["values"]["port"], "COM3")

    def test_need_selection_calls_fail(self):
        calls = []
        with mock.patch.object(serial_runtime, "get_serial_config",
                               return_value=(None, {"need_selection": True,
                                                    "error": "找到多个串口"})):
            out = serial_runtime.resolve_serial_config(
                self._args(), fail=lambda c, m: calls.append((c, m)))
        self.assertIsNone(out)
        self.assertEqual(calls[0][0], "multiple_candidates")

    def test_config_error_calls_fail(self):
        calls = []
        with mock.patch.object(serial_runtime, "get_serial_config",
                               return_value=(None, {"error": "未找到可用串口"})):
            serial_runtime.resolve_serial_config(
                self._args(), fail=lambda c, m: calls.append((c, m)))
        self.assertEqual(calls[0], ("config_error", "未找到可用串口"))


class ConnectSerialTests(unittest.TestCase):
    def _args(self, direct=False):
        return SimpleNamespace(direct=direct)

    def test_mux_connection_warns(self):
        ser = SimpleNamespace(_serial_skill_using_mux=True)
        err = io.StringIO()
        with mock.patch.object(serial_runtime, "open_serial_port", return_value=ser), \
                redirect_stderr(err):
            out = serial_runtime.connect_serial({}, self._args(), mux_warn="WARN", fail=lambda c, m: None)
        self.assertIs(out, ser)
        self.assertIn("WARN", err.getvalue())

    def test_connection_error_calls_fail(self):
        calls = []
        with mock.patch.object(serial_runtime, "open_serial_port",
                               side_effect=OSError("denied")):
            out = serial_runtime.connect_serial(
                {}, self._args(), mux_warn="W", fail=lambda c, m: calls.append((c, m)))
        self.assertIsNone(out)
        self.assertEqual(calls[0][0], "connect_failed")


class MuxProbeTests(unittest.TestCase):
    def test_windows_tcp_probe_alive(self):
        class _Sock:
            def __enter__(self):
                return self

            def __exit__(self, *_x):
                return False

            def settimeout(self, _t):
                pass

            def connect_ex(self, _addr):
                return 0

        class _SockModule:
            AF_INET = 2
            SOCK_STREAM = 1

            @staticmethod
            def socket(*_a):
                return _Sock()

        old_socket, old_os = serial_runtime.socket, serial_runtime.os
        serial_runtime.socket = _SockModule
        serial_runtime.os = SimpleNamespace(name="nt")
        try:
            self.assertTrue(serial_runtime.is_mux_alive({"tcp_port": 20001}))
            self.assertFalse(serial_runtime.is_mux_alive({}))
        finally:
            serial_runtime.socket, serial_runtime.os = old_socket, old_os

    def test_posix_probe_uses_kill(self):
        killed = []

        def _kill(pid, sig):
            killed.append(pid)
            if pid == 99:
                raise ProcessLookupError()

        old_os = serial_runtime.os
        serial_runtime.os = SimpleNamespace(name="posix", kill=_kill)
        try:
            self.assertTrue(serial_runtime.is_mux_alive({"tcp_pid": 1, "pty_pid": 2}))
            self.assertFalse(serial_runtime.is_mux_alive({"tcp_pid": 99}))
            self.assertFalse(serial_runtime.is_mux_alive({}))
        finally:
            serial_runtime.os = old_os

    def test_get_mux_info_returns_alive(self):
        info = {"tcp_port": 20001}
        with mock.patch.object(serial_runtime, "load_workspace_state",
                               return_value={"serial_mux": info}), \
                mock.patch.object(serial_runtime, "is_mux_alive", return_value=True):
            self.assertEqual(serial_runtime.get_mux_info(), info)

    def test_get_mux_info_cleans_stale(self):
        saved = []
        with mock.patch.object(serial_runtime, "load_workspace_state",
                               return_value={"serial_mux": {"tcp_port": 1}}), \
                mock.patch.object(serial_runtime, "is_mux_alive", return_value=False), \
                mock.patch.object(serial_runtime, "state_write_lock"), \
                mock.patch.object(serial_runtime, "load_workspace_state_for_update",
                                  return_value={"serial_mux": {}}), \
                mock.patch.object(serial_runtime, "save_workspace_state",
                                  side_effect=lambda *a: saved.append(a)):
            self.assertIsNone(serial_runtime.get_mux_info())
        self.assertEqual(saved[0][0], {})

    def test_config_matches_mux(self):
        cfg = {"port": "COM3", "baudrate": 115200, "bytesize": 8,
               "parity": "none", "stopbits": 1}
        mux = {"real_port": "COM3", "baudrate": 115200, "bytesize": 8,
               "parity": "none", "stopbits": 1}
        self.assertTrue(serial_runtime.config_matches_mux(cfg, mux))
        self.assertFalse(serial_runtime.config_matches_mux(dict(cfg, port="COM4"), mux))
        self.assertFalse(serial_runtime.config_matches_mux(dict(cfg, baudrate=9600), mux))


if __name__ == "__main__":
    unittest.main()
