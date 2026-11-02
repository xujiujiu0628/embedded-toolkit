r"""F-241: serial_mux 服务本体（广播/客户端循环/启动失败/关闭）补测。

## 覆盖对象

`scripts/serial_mux.py` 此前 50% 覆盖（2026-11-02 实测）：`SerialMuxServer`
的 run 失败/成功路径、accept/serial/client 三个循环、广播与关闭，以及
`run_mux_server` 未执行。

## 夹具

- `serial` 用 sys.modules 注入假模块（`import serial` 在 run 内）；
- socket / time / os 用直接赋值替身（避免 test_stub_ratchet 的 B 式判据），
  用完还原；
- 线程只跑到 stop_event 被置位即退出，不做真实 TCP 收发。
"""
import io
import os
import socket
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_mux  # noqa: E402


class _FakeSerial:
    def __init__(self, data=b"", raise_on_read=None):
        self.data = data
        self.raise_on_read = raise_on_read
        self.written = []
        self.flushed = 0
        self.closed = False
        self.in_waiting = len(data)

    def read(self, _n):
        if self.raise_on_read:
            raise self.raise_on_read
        data, self.data = self.data, b""
        return data

    def write(self, payload):
        self.written.append(bytes(payload))

    def flush(self):
        self.flushed += 1

    def close(self):
        self.closed = True


class _FakeServerSock:
    def __init__(self, accept_side_effect=None):
        self.accept_side_effect = accept_side_effect
        self.closed = False

    def setsockopt(self, *_a):
        pass

    def bind(self, _addr):
        pass

    def listen(self):
        pass

    def settimeout(self, _t):
        pass

    def accept(self):
        if self.accept_side_effect:
            raise self.accept_side_effect
        raise socket.timeout()

    def close(self):
        self.closed = True


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


class _FakeClient:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []
        self.closed = False

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        if self.chunks:
            return self.chunks.pop(0)
        raise socket.timeout()

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True


def _cfg():
    return {"port": "COM3", "baudrate": 115200, "bytesize": 8,
            "parity": "none", "stopbits": 1}


class ServerMethodTests(unittest.TestCase):
    def test_broadcast_sends_and_drops_dead_clients(self):
        server = serial_mux.SerialMuxServer(_cfg(), 20001)
        good = _FakeClient([])
        bad = _FakeClient([])

        def _boom(_data):
            raise OSError("dead")

        bad.sendall = _boom
        server.clients = {good, bad}
        server._broadcast(b"hi")
        self.assertEqual(good.sent, [b"hi"])
        self.assertNotIn(bad, server.clients)
        self.assertTrue(bad.closed)

    def test_remove_client_closes(self):
        server = serial_mux.SerialMuxServer(_cfg(), 20001)
        client = _FakeClient([])
        server.clients = {client}
        server._remove_client(client)
        self.assertNotIn(client, server.clients)
        self.assertTrue(client.closed)

    def test_client_loop_writes_then_removes(self):
        server = serial_mux.SerialMuxServer(_cfg(), 20001)
        server.serial_port = _FakeSerial()
        client = _FakeClient([b"abc", b""])
        server._client_read_loop(client)
        self.assertEqual(server.serial_port.written, [b"abc"])
        self.assertEqual(server.serial_port.flushed, 1)
        self.assertNotIn(client, server.clients)

    def test_close_closes_everything(self):
        server = serial_mux.SerialMuxServer(_cfg(), 20001)
        client = _FakeClient([])
        server.clients = {client}
        server.server_sock = _FakeServerSock()
        server.serial_port = _FakeSerial()
        server.close()
        self.assertTrue(client.closed)
        self.assertTrue(server.server_sock.closed)
        self.assertTrue(server.serial_port.closed)
        self.assertTrue(server.stop_event.is_set())

    def test_accept_loop_exits_on_oserror(self):
        server = serial_mux.SerialMuxServer(_cfg(), 20001)
        server.server_sock = _FakeServerSock(accept_side_effect=OSError("closed"))
        server._accept_loop()
        self.assertFalse(server.stop_event.is_set())


class RunTests(unittest.TestCase):
    def _inject_serial(self, serial_obj):
        module = types.ModuleType("serial")
        module.Serial = lambda **_kw: serial_obj
        old = sys.modules.get("serial")
        sys.modules["serial"] = module

        def restore():
            if old is None:
                sys.modules.pop("serial", None)
            else:
                sys.modules["serial"] = old
        return restore

    def test_serial_open_failure_returns_one(self):
        class _BadSerial:
            def __init__(self, **_kw):
                raise OSError("no port")

        module = types.ModuleType("serial")
        module.Serial = _BadSerial
        old = sys.modules.get("serial")
        sys.modules["serial"] = module
        err = io.StringIO()
        try:
            with redirect_stderr(err):
                rc = serial_mux.SerialMuxServer(_cfg(), 20001).run()
        finally:
            if old is None:
                sys.modules.pop("serial", None)
            else:
                sys.modules["serial"] = old
        self.assertEqual(rc, 1)
        self.assertIn("mux serve failed", err.getvalue())

    def test_success_path_stops_via_event(self):
        serial_obj = _FakeSerial()
        restore_serial = self._inject_serial(serial_obj)
        server_sock = _FakeServerSock()
        old_socket = serial_mux.socket
        old_time = serial_mux.time
        serial_mux.socket = _FakeSockModule(server_sock)
        server = serial_mux.SerialMuxServer(_cfg(), 20001)
        serial_mux.time = SimpleNamespace(
            sleep=lambda _s: server.stop_event.set(),
            time=old_time.time, strftime=old_time.strftime)
        try:
            rc = server.run()
        finally:
            serial_mux.socket = old_socket
            serial_mux.time = old_time
            restore_serial()
        self.assertEqual(rc, 0)
        self.assertTrue(server_sock.closed)
        self.assertTrue(serial_obj.closed)

    def test_serial_read_loop_failure_writes_marker(self):
        server = serial_mux.SerialMuxServer(_cfg(), 20999)
        server.serial_port = _FakeSerial(raise_on_read=OSError("boom"))
        exited = []
        old_os = serial_mux.os
        serial_mux.os = SimpleNamespace(_exit=lambda code: exited.append(code))
        err = io.StringIO()
        try:
            with redirect_stderr(err):
                server._serial_read_loop()
        finally:
            serial_mux.os = old_os
        self.assertEqual(exited, [1])
        self.assertIn("serial read loop died", err.getvalue())
        marker = os.path.join(tempfile.gettempdir(), "serial_mux", "serve_20999.failed")
        self.assertTrue(os.path.isfile(marker))
        os.remove(marker)


if __name__ == "__main__":
    unittest.main()
