r"""F-238: openocd_itm 主流程补测（参数解析 / 服务启动 / trace 循环 / 错误出口）。

## 覆盖对象

`scripts/openocd_itm.py` 此前 32% 覆盖（2026-11-02 实测）：`main()` 整段
（~225 行）从未执行。本文件用模块引用替换把 OpenOCD 进程、ITM 就绪探测与
trace socket 全部假化，跑通成功路径与五条错误出口，不碰探针。

## 夹具

- `_FakeProc.poll()` 返回 0 → trace 循环在 socket.timeout 时退出；
- `_FakeSock` 先吐一块数据再抛 `socket.timeout`；
- 所有 runtime 依赖（resolve_param / resolve_openocd_params /
  start_openocd_server / wait_itm_ready / emit_stream_record / cleanup /
  update_state_entry / save_project_config）均为模块引用替换。
"""
import io
import json
import os
import socket
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_itm  # noqa: E402


class _FakeProc:
    def __init__(self, rc=0):
        self.rc = rc

    def poll(self):
        return self.rc


class _FakeSock:
    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.closed = False

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        if self.chunks:
            return self.chunks.pop(0)
        raise socket.timeout()

    def close(self):
        self.closed = True


def _params(**overrides):
    base = {
        "board": "board/stm32f103.cfg", "board_source": "cli",
        "interface": "", "interface_source": "cli",
        "target": "", "target_source": "cli",
        "adapter_speed": "", "adapter_speed_source": "cli",
        "transport": "", "transport_source": "cli",
        "tpiu_name": "tpiu", "tpiu_name_source": "cli",
        "traceclk": "1000000", "traceclk_source": "cli",
        "pin_freq": "", "pin_freq_source": "cli",
    }
    base.update(overrides)
    return base


class _FakeSocketModule:
    """socket 模块替身（直接赋值替换，不用 mock.patch —— 后者会被
    test_stub_ratchet 记为 B 式全局打桩）。"""

    timeout = socket.timeout

    def __init__(self, connect):
        self.create_connection = connect


def _run_main(argv, *, params=None, resolve_param=None, ready=(True, []),
              start_exc=None, connect_exc=None, sock_chunks=(b"itm-line",)):
    """进程内跑 main(): 返回 (rc, stdout, stderr, 记录)。"""
    records = {"state": [], "config": [], "stream": [], "cleanup": []}
    out, err = io.StringIO(), io.StringIO()
    fake_proc = _FakeProc()
    fake_sock = _FakeSock(sock_chunks)

    def _start(*_a, **_k):
        if start_exc:
            raise start_exc
        return fake_proc

    def _connect(*_a, **_k):
        if connect_exc:
            raise connect_exc
        return fake_sock

    rp = resolve_param or (lambda name, *a, **k: ("openocd", "cli"))
    old_argv = sys.argv
    old_socket = openocd_itm.socket
    sys.argv = ["openocd_itm.py", *argv]
    openocd_itm.socket = _FakeSocketModule(_connect)
    try:
        with ExitStack() as stack:
            def patch(obj, name, **kwargs):
                stack.enter_context(mock.patch.object(obj, name, **kwargs))

            patch(openocd_itm, "workspace_root", return_value=tempfile.gettempdir())
            patch(openocd_itm, "default_config_path", return_value="cfg.json")
            patch(openocd_itm, "normalize_path", side_effect=str)
            patch(openocd_itm, "load_json_file", return_value={})
            patch(openocd_itm, "load_workspace_state", return_value={})
            patch(openocd_itm, "load_project_config", return_value={})
            patch(openocd_itm, "_state_lookup", return_value={})
            patch(openocd_itm, "resolve_openocd_params",
                  return_value=params if params is not None else _params())
            patch(openocd_itm, "resolve_param", side_effect=rp)
            patch(openocd_itm, "build_openocd_cmd", return_value=["openocd"])
            patch(openocd_itm, "start_openocd_server", side_effect=_start)
            patch(openocd_itm, "wait_itm_ready", return_value=ready)
            patch(openocd_itm, "emit_stream_record",
                  side_effect=lambda **kw: records["stream"].append(kw))
            patch(openocd_itm, "update_state_entry",
                  side_effect=lambda *a, **k: records["state"].append(a))
            patch(openocd_itm, "save_project_config",
                  side_effect=lambda *a, **k: records["config"].append(a))
            patch(openocd_itm, "cleanup",
                  side_effect=lambda p: records["cleanup"].append(p))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            try:
                rc = openocd_itm.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old_argv
        openocd_itm.socket = old_socket
    return rc, out.getvalue(), err.getvalue(), records, fake_sock


class ItmMainTests(unittest.TestCase):
    def test_success_streams_records_and_persists_config(self):
        rc, _, _, records, sock = _run_main(["--board", "b.cfg", "--json"])
        self.assertIsNone(rc)
        self.assertEqual(records["stream"][0]["text"], "itm-line")
        self.assertEqual(records["state"][0][0], "last_observe")
        self.assertEqual(records["config"][0][1]["board"], "board/stm32f103.cfg")
        self.assertEqual(len(records["cleanup"]), 1)
        self.assertTrue(sock.closed)

    def test_missing_param_exits_one(self):
        def _raise(*_a, **_k):
            raise ValueError("exe 缺失")

        rc, _, err, _, _ = _run_main(["--board", "b.cfg"], resolve_param=_raise)
        self.assertEqual(rc, 1)
        self.assertIn("exe 缺失", err)

    def test_missing_board_and_target_exits_one(self):
        params = _params(board="", interface="", target="")
        rc, _, err, _, _ = _run_main([], params=params)
        self.assertEqual(rc, 1)
        self.assertIn("必须提供", err)

    def test_server_not_ready_exits_one(self):
        rc, _, err, _, _ = _run_main(
            ["--board", "b.cfg"], ready=(False, ["boom line"]))
        self.assertEqual(rc, 1)
        self.assertIn("boom line", err)

    def test_exe_not_found_exits_one(self):
        rc, _, err, _, _ = _run_main(
            ["--board", "b.cfg"], start_exc=FileNotFoundError())
        self.assertEqual(rc, 1)
        self.assertIn("openocd 不存在", err)

    def test_trace_connect_failure_exits_one(self):
        rc, _, err, _, _ = _run_main(
            ["--board", "b.cfg"], connect_exc=OSError("refused"))
        self.assertEqual(rc, 1)
        self.assertIn("trace 连接失败", err)

    def test_json_error_output(self):
        params = _params(board="", interface="", target="")
        rc, out, _, _, _ = _run_main(["--json"], params=params)
        self.assertEqual(rc, 1)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "missing_config")


class BuildCmdTests(unittest.TestCase):
    def test_board_path_and_itm_ports(self):
        cmd = openocd_itm.build_openocd_cmd(
            "openocd", board="b.cfg", trace_port=3443,
            tpiu_name="tpiu", traceclk="1000000", itm_ports=["0", "1"])
        self.assertEqual(cmd[0], "openocd")
        self.assertIn("-f", cmd)
        self.assertIn("b.cfg", cmd)
        self.assertIn("tpiu configure -protocol uart -output :3443 -traceclk 1000000", cmd)
        self.assertIn("itm port 0 on", cmd)
        self.assertIn("itm port 1 on", cmd)
        self.assertNotIn("itm ports on", cmd)

    def test_interface_and_target_when_no_board(self):
        cmd = openocd_itm.build_openocd_cmd(
            "openocd", interface="i.cfg", target="t.cfg",
            tpiu_name="tpiu", traceclk="1")
        self.assertIn("i.cfg", cmd)
        self.assertIn("t.cfg", cmd)

    def test_search_speed_transport_and_pin_freq(self):
        cmd = openocd_itm.build_openocd_cmd(
            "openocd", board="b.cfg", search="/s", adapter_speed="1000",
            transport="swd", tpiu_name="tpiu", traceclk="1", pin_freq="2000000")
        self.assertIn("/s", cmd)
        self.assertIn("adapter speed 1000", cmd)
        self.assertIn("transport select swd", cmd)
        self.assertIn("tpiu configure -protocol uart -output :3443 -traceclk 1 -pin-freq 2000000", cmd)

    def test_defaults_enable_all_itm_ports(self):
        cmd = openocd_itm.build_openocd_cmd(
            "openocd", board="b.cfg", tpiu_name="tpiu", traceclk="1")
        self.assertIn("itm ports on", cmd)
        self.assertIn("gdb_port 3333", cmd)
        self.assertIn("telnet_port 4444", cmd)


class ResolveParamsTests(unittest.TestCase):
    def _args(self, **kw):
        import argparse
        base = dict(board=None, interface=None, target=None, adapter_speed=None,
                    transport=None, tpiu_name=None, traceclk=None, pin_freq=None)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_cli_wins(self):
        out = openocd_itm.resolve_openocd_params(
            self._args(board="cli.cfg"), {"board": "proj.cfg"}, {"board": "state.cfg"})
        self.assertEqual(out["board"], "cli.cfg")
        self.assertEqual(out["board_source"], "cli")

    def test_project_config_second(self):
        out = openocd_itm.resolve_openocd_params(
            self._args(), {"board": "proj.cfg"}, {"board": "state.cfg"})
        self.assertEqual(out["board"], "proj.cfg")
        self.assertEqual(out["board_source"], "project_config")

    def test_state_third(self):
        out = openocd_itm.resolve_openocd_params(
            self._args(), {}, {"board": "state.cfg"})
        self.assertEqual(out["board"], "state.cfg")
        self.assertEqual(out["board_source"], "state")

    def test_tpiu_fields_only_cli_or_project(self):
        out = openocd_itm.resolve_openocd_params(
            self._args(), {"tpiu_name": "proj.tpiu", "traceclk": "2000000",
                           "pin_freq": "4000000"}, {})
        self.assertEqual(out["tpiu_name"], "proj.tpiu")
        self.assertEqual(out["tpiu_name_source"], "project_config")
        self.assertEqual(out["traceclk"], "2000000")
        self.assertEqual(out["pin_freq"], "4000000")

    def test_empty_sources_reported(self):
        out = openocd_itm.resolve_openocd_params(self._args(), {}, {})
        self.assertIsNone(out["board"])
        self.assertEqual(out["board_source"], "state")


if __name__ == "__main__":
    unittest.main()
