r"""F-238: serial_mux 的端口探测、状态查询、停止与 CLI 派发补测。

## 覆盖对象

`scripts/serial_mux.py` 此前 37% 覆盖（2026-11-02 实测）：`find_free_port` /
`wait_for_tcp_server` / `status_mux` / `stop_mux` / `main` 均未执行。服务本体
（`SerialMuxServer.run` 的真串口转发）仍需真实端口，不在本批范围。

## 夹具

- state 读改写用模块引用替换（`load_workspace_state_for_update` /
  `_mutate_mux_state` / `is_mux_alive`）；
- `os` 用只代理 `path`、覆写 `kill` 的替身直接赋值（避免 test_stub_ratchet
  的 B 式全局打桩判据）；
- socket 同样直接赋值替换，不绑真实端口（`find_free_port` 的成功路径除外）。
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_mux  # noqa: E402


class _CaptureOut(io.StringIO):
    def reconfigure(self, **_kwargs):
        pass


class _FakeOs:
    path = os.path

    def __init__(self, kill=None):
        self.kill_calls = []
        self._kill = kill

    def kill(self, pid, sig):
        self.kill_calls.append((pid, sig))
        if self._kill:
            self._kill(pid, sig)


class _FakeProc:
    def __init__(self, rc=None):
        self.rc = rc

    def poll(self):
        return self.rc


class _FakeSocketModule:
    AF_INET = 2
    SOCK_STREAM = 1

    def __init__(self, bind_exc=None, connect_exc=None):
        self.bind_exc = bind_exc
        self.connect_exc = connect_exc
        self.bound = []

    def socket(self, *_a):
        outer = self

        class _S:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_x):
                return False

            def bind(self_inner, addr):
                if outer.bind_exc:
                    raise outer.bind_exc
                outer.bound.append(addr)

        return _S()

    def create_connection(self, addr, timeout=None):
        if self.connect_exc:
            raise self.connect_exc
        return _FakeSock()


class _FakeSock:
    def __enter__(self):
        return self

    def __exit__(self, *_x):
        return False


class FindFreePortTests(unittest.TestCase):
    def test_returns_first_bindable_port(self):
        port = serial_mux.find_free_port(56000)
        self.assertGreaterEqual(port, 56000)

    def test_returns_start_when_all_bind_fail(self):
        old = serial_mux.socket
        serial_mux.socket = _FakeSocketModule(bind_exc=OSError("busy"))
        try:
            self.assertEqual(serial_mux.find_free_port(56000), 56000)
        finally:
            serial_mux.socket = old


class WaitForServerTests(unittest.TestCase):
    def test_returns_true_when_connectable(self):
        old = serial_mux.socket
        serial_mux.socket = _FakeSocketModule()
        try:
            self.assertTrue(serial_mux.wait_for_tcp_server(1, _FakeProc(), timeout=0.1))
        finally:
            serial_mux.socket = old

    def test_returns_false_when_process_exited(self):
        old = serial_mux.socket
        serial_mux.socket = _FakeSocketModule()
        try:
            self.assertFalse(serial_mux.wait_for_tcp_server(1, _FakeProc(rc=1), timeout=0.1))
        finally:
            serial_mux.socket = old


class StatusMuxTests(unittest.TestCase):
    def _run(self, state, alive=True):
        with mock.patch.object(serial_mux, "load_workspace_state_for_update", return_value=state), \
                mock.patch.object(serial_mux, "_mutate_mux_state") as mutate, \
                mock.patch.object(serial_mux, "is_mux_alive", return_value=alive):
            result = serial_mux.status_mux(None)
        return result, mutate

    def test_not_running(self):
        result, _ = self._run({})
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["details"]["running"])
        self.assertIn("未运行", result["summary"])

    def test_running_reports_fields(self):
        info = {"real_port": "COM3", "tcp_port": 20001, "vserial": "COM10",
                "baudrate": 115200, "started_at": "t"}
        result, _ = self._run({"serial_mux": info})
        self.assertTrue(result["details"]["running"])
        self.assertEqual(result["details"]["real_port"], "COM3")
        self.assertIn("COM3", result["summary"])

    def test_stale_state_is_cleaned(self):
        result, mutate = self._run({"serial_mux": {"real_port": "COM3"}}, alive=False)
        self.assertFalse(result["details"]["running"])
        self.assertTrue(result["details"]["cleaned"])
        mutate.assert_called_once()


class StopMuxTests(unittest.TestCase):
    def _run(self, state, kill=None):
        fake_os = _FakeOs(kill=kill)
        old_os = serial_mux.os
        serial_mux.os = fake_os
        try:
            with mock.patch.object(serial_mux, "load_workspace_state_for_update", return_value=state), \
                    mock.patch.object(serial_mux, "_mutate_mux_state") as mutate:
                result = serial_mux.stop_mux(None)
        finally:
            serial_mux.os = old_os
        return result, fake_os, mutate

    def test_not_running(self):
        result, _, _ = self._run({})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "not_running")

    def test_kills_both_pids_and_clears_state(self):
        state = {"serial_mux": {"tcp_pid": 11, "pty_pid": 22, "vserial": None}}
        result, fake_os, mutate = self._run(state)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([c[0] for c in fake_os.kill_calls], [11, 22])
        self.assertEqual(len(result["details"]["killed"]), 2)
        mutate.assert_called_once()

    def test_missing_pid_is_ignored(self):
        def _gone(_pid, _sig):
            raise ProcessLookupError()

        state = {"serial_mux": {"tcp_pid": 11, "vserial": None}}
        result, fake_os, _ = self._run(state, kill=_gone)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"]["killed"], [])

    def test_kill_failure_reported(self):
        def _boom(_pid, _sig):
            raise RuntimeError("denied")

        state = {"serial_mux": {"tcp_pid": 11, "vserial": None}}
        result, _, _ = self._run(state, kill=_boom)
        self.assertIn("1 个失败", result["summary"])
        self.assertEqual(result["details"]["failed"], ["11"])


class MainDispatchTests(unittest.TestCase):
    def _run(self, argv, status_result=None):
        out, err = _CaptureOut(), io.StringIO()
        old_argv = sys.argv
        sys.argv = ["serial_mux.py", *argv]
        try:
            with mock.patch.object(serial_mux, "status_mux",
                                   return_value=status_result or {"status": "ok", "details": {"running": False}}), \
                    mock.patch.object(serial_mux, "stop_mux",
                                      return_value={"status": "ok", "details": {}}), \
                    redirect_stdout(out), redirect_stderr(err):
                try:
                    rc = serial_mux.main()
                except SystemExit as exc:
                    rc = exc.code if exc.code is not None else 0
        finally:
            sys.argv = old_argv
        return rc, out.getvalue()

    def test_status_command_exit_zero(self):
        rc, out = self._run(["status"])
        self.assertEqual(rc, 0)
        self.assertIn('"status": "ok"', out)

    def test_stop_command_exit_zero(self):
        rc, _ = self._run(["stop"])
        self.assertEqual(rc, 0)

    def test_no_command_reports_not_running(self):
        rc, out = self._run([])
        self.assertEqual(rc, 0)
        self.assertIn("未运行", out)


if __name__ == "__main__":
    unittest.main()
