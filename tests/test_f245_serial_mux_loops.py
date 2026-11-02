r"""F-245: serial_mux 的服务循环 / 关闭异常 / serve 子命令补测。

## 覆盖对象

`scripts/serial_mux.py` 此前 86% 覆盖（2026-11-02 实测）：`wait_for_tcp_server`
的进程退出、accept 循环的客户端接入与断开、client 循环异常、serial 读循环
的成功广播、close 的异常吞并、stop 的 unlink 失败、main 的 `serve` 分支。
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_mux  # noqa: E402


class _Proc:
    def __init__(self, rc=None):
        self.rc = rc

    def poll(self):
        return self.rc


class _ServerSock:
    def __init__(self, items):
        self.items = list(items)
        self.closed = False

    def accept(self):
        item = self.items.pop(0) if self.items else OSError("closed")
        if isinstance(item, Exception):
            raise item
        return item, ("127.0.0.1", 1)

    def settimeout(self, _t):
        pass

    def close(self):
        raise OSError("close failed")


class _Client:
    def __init__(self, chunks=None, exc=None):
        self.chunks = list(chunks or [])
        self.exc = exc
        self.closed = False

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        if self.exc:
            raise self.exc
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        raise OSError("client close failed")


class LoopTests(unittest.TestCase):
    def test_wait_for_server_process_exits(self):
        self.assertFalse(serial_mux.wait_for_tcp_server(1, _Proc(rc=1), timeout=0.1))

    def test_accept_loop_adds_client_then_exits(self):
        class _NoThread:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

        server = serial_mux.SerialMuxServer({"port": "x"}, 20001)
        client = _Client()
        server.server_sock = _ServerSock([client, OSError("closed")])
        old = serial_mux.threading
        serial_mux.threading = SimpleNamespace(
            Thread=_NoThread, Lock=old.Lock, Event=old.Event)
        try:
            server._accept_loop()
        finally:
            serial_mux.threading = old
        self.assertIn(client, server.clients)

    def test_client_loop_exception_sets_stop(self):
        server = serial_mux.SerialMuxServer({"port": "x"}, 20001)
        server.serial_port = SimpleNamespace()
        client = _Client(exc=RuntimeError("boom"))
        server._client_read_loop(client)
        self.assertTrue(server.stop_event.is_set())
        self.assertNotIn(client, server.clients)

    def test_serial_read_loop_broadcasts(self):
        server = serial_mux.SerialMuxServer({"port": "x"}, 20001)
        sent = []
        server.serial_port = SimpleNamespace(in_waiting=2, read=lambda _n: b"ab")
        server._broadcast = lambda data: sent.append(data)
        old = server.stop_event
        server.stop_event = SimpleNamespace(is_set=lambda: bool(sent), set=lambda: None,
                                           wait=lambda *_a: None)
        try:
            server._serial_read_loop()
        finally:
            server.stop_event = old
        self.assertEqual(sent, [b"ab"])

    def test_close_swallows_socket_errors(self):
        server = serial_mux.SerialMuxServer({"port": "x"}, 20001)
        client = _Client()
        server.clients = {client}
        server.server_sock = _ServerSock([])
        server.serial_port = SimpleNamespace(close=lambda: (_ for _ in ()).throw(OSError()))
        server.close()   # 不应抛出
        self.assertTrue(server.stop_event.is_set())


class StopUnlinkFailureTests(unittest.TestCase):
    def test_unlink_error_ignored(self):
        fake_os = SimpleNamespace(
            path=SimpleNamespace(islink=lambda _p: True),
            unlink=lambda _p: (_ for _ in ()).throw(OSError("locked")),
            kill=lambda pid, sig: None)
        old = serial_mux.os
        serial_mux.os = fake_os
        try:
            with mock.patch.object(serial_mux, "load_workspace_state_for_update",
                                   return_value={serial_mux.STATE_KEY:
                                                 {"vserial": "/tmp/v"}}), \
                    mock.patch.object(serial_mux, "_mutate_mux_state"):
                result = serial_mux.stop_mux(None)
        finally:
            serial_mux.os = old
        self.assertEqual(result["status"], "ok")


class ServeCommandTests(unittest.TestCase):
    def test_serve_dispatches_to_server(self):
        calls = []
        old = sys.argv
        sys.argv = ["serial_mux.py", "serve", "--port", "COM3", "--baudrate", "115200",
                    "--bytesize", "8", "--parity", "none", "--stopbits", "1",
                    "--tcp-port", "20001"]
        try:
            with mock.patch.object(serial_mux, "run_mux_server",
                                   side_effect=lambda cfg, port: calls.append((cfg, port)) or 0):
                try:
                    serial_mux.main()
                except SystemExit as exc:
                    rc = exc.code
        finally:
            sys.argv = old
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0][1], 20001)


if __name__ == "__main__":
    unittest.main()
