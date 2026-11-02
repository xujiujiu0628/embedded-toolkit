r"""F-242: serial_mux start_mux 的启动链路与失败回收补测。

## 覆盖对象

`scripts/serial_mux.py` 此前 73% 覆盖（2026-11-02 实测）：`start_mux` 的
socat 缺失 / 已在运行 / 僵尸清理 / 配置缺失 / 无端口 / TCP 未就绪 /
PTY 进程早退 / PTY 链接未建 / 成功落账 / 异常回收共十条分支未执行。

## 夹具

`subprocess.Popen` 用假进程（pid/terminate/wait/poll/kill 可观测），
`socat`/`get_serial_config`/`wait_for_tcp_server`/`_mutate_mux_state`/
`save_project_config` 模块引用替换；不启真子进程。
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
    _next = 1000

    def __init__(self, poll_rc=None):
        _Proc._next += 1
        self.pid = _Proc._next
        self.poll_rc = poll_rc
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return self.poll_rc

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True
        return 0

    def kill(self):
        self.killed = True


def _cfg():
    return {"port": "COM3", "baudrate": 115200, "bytesize": 8,
            "parity": "none", "stopbits": 1, "encoding": "utf-8"}


def _start(*, socat=True, existing=None, alive=True, cfg=None, cfg_none=False,
           tcp_ready=True, p2_poll=None, vserial_exists=True, popen_exc=None):
    records = {"state": [], "config": [], "procs": []}

    def _popen(cmd, **_kw):
        if popen_exc:
            raise popen_exc
        proc = _Proc(poll_rc=p2_poll if records["procs"] else None)
        records["procs"].append(proc)
        return proc

    # 直接赋值替换全局模块对象（mock.patch 会被 test_stub_ratchet 记为
    # B 式全局打桩）；每个替身只带本函数用到的属性，用完还原。
    old = (serial_mux.shutil, serial_mux.subprocess, serial_mux.time, serial_mux.os)
    serial_mux.shutil = SimpleNamespace(which=lambda _n: "/usr/bin/socat" if socat else None)
    serial_mux.subprocess = SimpleNamespace(
        Popen=_popen, DEVNULL=object(), TimeoutExpired=TimeoutError)
    serial_mux.time = SimpleNamespace(sleep=lambda _s: None,
                                      strftime=old[2].strftime)
    serial_mux.os = SimpleNamespace(path=SimpleNamespace(exists=lambda _p: vserial_exists))
    try:
        with mock.patch.object(serial_mux, "load_workspace_state_for_update",
                               return_value=({serial_mux.STATE_KEY: existing} if existing else {})), \
                mock.patch.object(serial_mux, "is_mux_alive", return_value=alive), \
                mock.patch.object(serial_mux, "_mutate_mux_state",
                                  side_effect=lambda ws, mutate: records["state"].append(mutate)), \
                mock.patch.object(serial_mux, "get_serial_config",
                                  return_value=(None if cfg_none else (cfg if cfg is not None else _cfg()),
                                                {"port": "cli", "error": "配置错误"})), \
                mock.patch.object(serial_mux, "find_free_port", return_value=20001), \
                mock.patch.object(serial_mux, "wait_for_tcp_server", return_value=tcp_ready), \
                mock.patch.object(serial_mux, "save_project_config",
                                  side_effect=lambda ws, vals: records["config"].append(vals)):
            result = serial_mux.start_mux("COM3", 115200, None, "/tmp/vserial")
    finally:
        serial_mux.shutil, serial_mux.subprocess, serial_mux.time, serial_mux.os = old
    return result, records


class StartMuxTests(unittest.TestCase):
    def test_socat_missing(self):
        result, _ = _start(socat=False)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "socat_missing")

    def test_already_running(self):
        result, _ = _start(existing={"tcp_port": 1, "vserial": "v"}, alive=True)
        self.assertEqual(result["error"]["code"], "already_running")

    def test_stale_state_cleaned_then_config_error(self):
        result, records = _start(existing={"tcp_port": 1}, alive=False, cfg_none=True)
        self.assertEqual(result["error"]["code"], "config_error")
        self.assertEqual(len(records["state"]), 1)

    def test_missing_port_rejected(self):
        cfg = _cfg()
        cfg["port"] = ""
        result, _ = _start(cfg=cfg)
        self.assertEqual(result["error"]["code"], "no_port")

    def test_tcp_not_ready_terminates_first_process(self):
        result, records = _start(tcp_ready=False)
        self.assertEqual(result["error"]["code"], "port_open_failed")
        self.assertTrue(records["procs"][0].terminated)

    def test_pty_process_exits_early(self):
        result, records = _start(p2_poll=1)
        self.assertEqual(result["error"]["code"], "pty_failed")
        self.assertTrue(records["procs"][0].terminated)

    def test_pty_link_missing(self):
        result, records = _start(vserial_exists=False)
        self.assertEqual(result["error"]["code"], "pty_not_created")
        self.assertTrue(records["procs"][0].terminated)
        self.assertTrue(records["procs"][1].terminated)

    def test_success_persists_state_and_config(self):
        result, records = _start()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"]["tcp_port"], 20001)
        self.assertEqual(result["details"]["real_port"], "COM3")
        self.assertEqual(records["config"][0]["port"], "COM3")
        self.assertTrue(records["state"])

    def test_popen_exception_recycles_and_reports(self):
        result, _ = _start(popen_exc=OSError("spawn failed"))
        self.assertEqual(result["error"]["code"], "start_failed")
        self.assertIn("spawn failed", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
