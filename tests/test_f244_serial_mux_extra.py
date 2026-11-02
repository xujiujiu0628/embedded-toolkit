r"""F-244: serial_mux 的启动超时强杀 / 异常回收 / 停止清理 / CLI 运行态输出补测。

## 覆盖对象

`scripts/serial_mux.py` 此前 82% 覆盖（2026-11-02 实测）：start_mux 的
TCP 未就绪后 `wait` 超时改 `kill`、异常回收里 `wait` 再抛的兜底、stop_mux
的 vserial 符号链接清理，以及 main 的 `start` 派发与"运行中"人读输出未执行。
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_mux  # noqa: E402


class _Proc:
    _next = 2000

    def __init__(self, kill_on_wait=False, raise_on_wait=False):
        _Proc._next += 1
        self.pid = _Proc._next
        self.terminated = False
        self.killed = False
        self.waited = False
        self.kill_on_wait = kill_on_wait
        self.raise_on_wait = raise_on_wait
        self.poll_rc = None

    def poll(self):
        return self.poll_rc

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True
        if self.raise_on_wait:
            raise OSError("wait failed")
        if self.kill_on_wait:
            raise TimeoutError("slow")
        return 0

    def kill(self):
        self.killed = True


def _cfg():
    return {"port": "COM3", "baudrate": 115200, "bytesize": 8,
            "parity": "none", "stopbits": 1, "encoding": "utf-8"}


def _start(wait_kill=False, wait_raise=False):
    procs = []

    def _popen(_cmd, **_kw):
        proc = _Proc(kill_on_wait=wait_kill, raise_on_wait=wait_raise)
        procs.append(proc)
        return proc

    old = (serial_mux.shutil, serial_mux.subprocess, serial_mux.time, serial_mux.os)
    serial_mux.shutil = SimpleNamespace(which=lambda _n: "/usr/bin/socat")
    serial_mux.subprocess = SimpleNamespace(Popen=_popen, DEVNULL=object(),
                                            TimeoutExpired=TimeoutError)
    serial_mux.time = SimpleNamespace(sleep=lambda _s: None,
                                      strftime=old[2].strftime)
    serial_mux.os = SimpleNamespace(path=SimpleNamespace(exists=lambda _p: True))
    try:
        with mock.patch.object(serial_mux, "load_workspace_state_for_update", return_value={}), \
                mock.patch.object(serial_mux, "is_mux_alive", return_value=True), \
                mock.patch.object(serial_mux, "_mutate_mux_state"), \
                mock.patch.object(serial_mux, "get_serial_config",
                                  return_value=(_cfg(), {})), \
                mock.patch.object(serial_mux, "find_free_port", return_value=20001), \
                mock.patch.object(serial_mux, "wait_for_tcp_server", return_value=False), \
                mock.patch.object(serial_mux, "save_project_config"):
            result = serial_mux.start_mux("COM3", 115200, None, "/tmp/v")
    finally:
        serial_mux.shutil, serial_mux.subprocess, serial_mux.time, serial_mux.os = old
    return result, procs


class StartTimeoutTests(unittest.TestCase):
    def test_wait_timeout_kills_process(self):
        result, procs = _start(wait_kill=True)
        self.assertEqual(result["error"]["code"], "port_open_failed")
        self.assertTrue(procs[0].killed)

    def test_exception_wait_swallowed(self):
        result, procs = _start(wait_raise=True)
        self.assertEqual(result["error"]["code"], "start_failed")
        self.assertTrue(procs[0].terminated)


class StopVserialTests(unittest.TestCase):
    def test_symlink_removed(self):
        unlinked = []
        fake_os = SimpleNamespace(
            path=SimpleNamespace(islink=lambda _p: True),
            unlink=lambda p: unlinked.append(p),
            kill=lambda pid, sig: None)
        old = serial_mux.os
        serial_mux.os = fake_os
        try:
            with mock.patch.object(serial_mux, "load_workspace_state_for_update",
                                   return_value={serial_mux.STATE_KEY:
                                                 {"tcp_pid": 1, "vserial": "/tmp/v"}}), \
                    mock.patch.object(serial_mux, "_mutate_mux_state"):
                result = serial_mux.stop_mux(None)
        finally:
            serial_mux.os = old
        self.assertEqual(result["status"], "ok")
        self.assertEqual(unlinked, ["/tmp/v"])


class MainExtraTests(unittest.TestCase):
    def _run(self, argv, **patches):
        out = io.StringIO()
        old = sys.argv
        sys.argv = ["serial_mux.py", *argv]
        try:
            with mock.patch.multiple(serial_mux, **patches):
                with redirect_stdout(out):
                    try:
                        rc = serial_mux.main()
                    except SystemExit as exc:
                        rc = exc.code if exc.code is not None else 0
        finally:
            sys.argv = old
        return rc, out.getvalue()

    def test_start_dispatch(self):
        rc, _ = self._run(["start", "--port", "COM3"],
                          start_mux=lambda *a, **k: {"status": "ok"})
        self.assertEqual(rc, 0)

    def test_no_command_running_prints_details(self):
        running = {"status": "ok", "details": {
            "running": True, "real_port": "COM3", "tcp_port": 20001,
            "vserial": "/tmp/v", "started_at": "t"}}
        rc, out = self._run([], status_mux=lambda *a, **k: running)
        self.assertEqual(rc, 0)
        self.assertIn("Mux 运行中", out)
        self.assertIn("虚拟串口", out)
        self.assertIn("启动时间", out)


if __name__ == "__main__":
    unittest.main()
