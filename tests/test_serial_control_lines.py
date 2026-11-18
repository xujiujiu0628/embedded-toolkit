r"""串口采集链开口即释放 DTR/RTS（与 esp_runtime F-177 同口径）。

## 覆盖对象

`scripts/serial_runtime.release_control_lines` 及三个开口点：

- `open_serial_port` 直连分支（串口服务族 STM32/CH32 走这条）
- `open_serial_port` mux 分支（socket:// 无控制线，属性赋值须被吞掉）
- `serial_mux.SerialMuxServer.run` 自己开的那个真实端口

## 为什么要有这组测试

pyserial 打开端口默认断言 DTR/RTS；CH340/CP210x 自动下载电路把该组合
当成复位。ESP 链 F-177 已单独堵住（`esp_runtime._release_lines`），通用
UART 采集链此前没有——板子会在读之前被按进复位，采集端只看到 0 行，
看起来像固件挂死。本组测试把"三个开口点都释放"钉成契约。

## 夹具

`serial` 用 sys.modules 注入假模块；socket/time 用直接赋值替身并在
finally 还原（同 test_f241 的做法，避免 test_stub_ratchet 的 B 式判据）。
"""
import os
import socket
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_mux      # noqa: E402
import serial_runtime  # noqa: E402


class _LineRecorder:
    """记录 dtr/rts 赋值的最小串口替身。"""

    def __init__(self, **_kwargs):
        self.dtr = None
        self.rts = None
        self.in_waiting = 0
        self.closed = False

    def read(self, _n):
        return b""

    def write(self, _payload):
        return None

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _NoControlLines:
    """没有控制线属性的后端（socket:// 一类）：赋值必须抛且被吞。"""

    __slots__ = ()

    def read(self, _n):
        return b""


class _Injectable:
    def __init__(self, **attrs):
        self.module = types.ModuleType("serial")
        for name, value in attrs.items():
            setattr(self.module, name, value)

    def __enter__(self):
        self._old = sys.modules.get("serial")
        sys.modules["serial"] = self.module
        return self

    def __exit__(self, *_exc):
        if self._old is None:
            sys.modules.pop("serial", None)
        else:
            sys.modules["serial"] = self._old
        return False


class _FakeServerSock:
    def setsockopt(self, *_a):
        pass

    def bind(self, _addr):
        pass

    def listen(self):
        pass

    def settimeout(self, _t):
        pass

    def close(self):
        pass


class _FakeSockModule:
    AF_INET = socket.AF_INET
    SOCK_STREAM = socket.SOCK_STREAM
    SOL_SOCKET = socket.SOL_SOCKET
    SO_REUSEADDR = socket.SO_REUSEADDR
    timeout = socket.timeout

    def __init__(self, server_sock):
        self.server_sock = server_sock

    def socket(self, *_a):
        return self.server_sock


class ReleaseControlLinesTests(unittest.TestCase):
    def test_direct_open_releases_both_lines(self):
        held = []

        def _factory(**kwargs):
            ser = _LineRecorder(**kwargs)
            held.append(ser)
            return ser

        with _Injectable(Serial=_factory):
            ser = serial_runtime.open_serial_port(
                {"port": "COM3", "baudrate": 115200, "bytesize": 8,
                 "parity": "none", "stopbits": 1, "timeout_sec": 1.0},
                use_mux=False)
        self.assertIs(ser, held[0])
        self.assertIs(ser.dtr, False)
        self.assertIs(ser.rts, False)

    def test_mux_open_releases_both_lines(self):
        ser = _LineRecorder()
        with _Injectable(serial_for_url=lambda _url: ser):
            with mock.patch.object(serial_runtime,
                                            "get_matching_mux_info",
                                            return_value={"tcp_port": 20001}):
                got = serial_runtime.open_serial_port(
                    {"port": "COM3", "timeout_sec": 2.0})
        self.assertIs(got, ser)
        self.assertIs(ser.dtr, False)
        self.assertIs(ser.rts, False)

    def test_backend_without_control_lines_does_not_raise(self):
        ser = _NoControlLines()
        serial_runtime.release_control_lines(ser)  # 不抛即通过

    def test_mux_server_releases_on_open(self):
        serial_obj = _LineRecorder()
        with _Injectable(Serial=lambda **_kw: serial_obj):
            old_socket, old_time = serial_mux.socket, serial_mux.time
            serial_mux.socket = _FakeSockModule(_FakeServerSock())
            server = serial_mux.SerialMuxServer(
                {"port": "COM3", "baudrate": 115200, "bytesize": 8,
                 "parity": "none", "stopbits": 1, "timeout_sec": 1.0}, 20001)
            serial_mux.time = SimpleNamespace(
                sleep=lambda _s: server.stop_event.set(),
                time=old_time.time, strftime=old_time.strftime)
            try:
                rc = server.run()
            finally:
                serial_mux.socket, serial_mux.time = old_socket, old_time
        self.assertEqual(rc, 0)
        self.assertIs(serial_obj.dtr, False)
        self.assertIs(serial_obj.rts, False)


if __name__ == "__main__":
    unittest.main()
