r"""F-245: openocd_gdb 的 gdb 缺失 / 非法参数 / cleanup 判定补测。

## 覆盖对象

`scripts/openocd_gdb.py` 此前 89% 覆盖（2026-11-02 实测）：`arm-none-eabi-gdb
不存在` 出口、`build_gdb_commands` 抛 ValueError 的 invalid_args 出口、
server 启动失败时 `cleanup` 仍执行的判定（F-121）、server 成功时跳过 cleanup。
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_gdb  # noqa: E402


class _FakeProc:
    pid = 7

    def wait(self):
        return 0


def _params(**over):
    base = {"board": "b.cfg", "board_source": "cli",
            "interface": "", "interface_source": "cli",
            "target": "", "target_source": "cli",
            "adapter_speed": "", "adapter_speed_source": "cli",
            "transport": "", "transport_source": "cli"}
    base.update(over)
    return base


def _run(argv, *, isfile=True, build_cmds_exc=None, start_exc=None,
         ready=(True, []), cleanup_calls=None):
    out, err = io.StringIO(), io.StringIO()
    cleanup_calls = cleanup_calls if cleanup_calls is not None else []

    def _start(*_a, **_k):
        if start_exc:
            raise start_exc
        return _FakeProc()

    old = sys.argv
    sys.argv = ["openocd_gdb.py", *argv]
    try:
        with ExitStack() as stack:
            def patch(obj, name, **kw):
                stack.enter_context(mock.patch.object(obj, name, **kw))

            ws = stack.enter_context(tempfile.TemporaryDirectory())
            patch(openocd_gdb, "workspace_root", return_value=ws)
            patch(openocd_gdb, "save_project_config")
            patch(openocd_gdb, "default_config_path", return_value="cfg.json")
            patch(openocd_gdb, "normalize_path", side_effect=str)
            patch(openocd_gdb, "load_json_file", return_value={})
            patch(openocd_gdb, "load_workspace_state", return_value={})
            patch(openocd_gdb, "_state_lookup", return_value={})
            patch(openocd_gdb, "load_project_config", return_value={})
            patch(openocd_gdb, "resolve_openocd_params", return_value=_params())
            patch(openocd_gdb, "resolve_param",
                  side_effect=lambda name, *_a, **_k: {
                      "exe": ("openocd", "cli"),
                      "gdb_exe": ("/fake/gdb", "cli"),
                      "elf": ("fw.elf", "cli")}.get(name, (None, "default")))
            patch(openocd_gdb, "which", return_value=None)
            patch(openocd_gdb, "build_openocd_cmd", return_value=["openocd"])
            patch(openocd_gdb, "start_openocd_server", side_effect=_start)
            patch(openocd_gdb, "wait_server_ready", return_value=ready)
            patch(openocd_gdb, "update_state_entry", return_value={})
            patch(openocd_gdb, "run_gdb_commands",
                  return_value={"status": "ok", "stdout": "", "returncode": 0})
            patch(openocd_gdb, "build_gdb_commands",
                  side_effect=build_cmds_exc,
                  return_value=["monitor halt"])
            patch(openocd_gdb, "cleanup",
                  side_effect=lambda p: cleanup_calls.append(p))
            patch(openocd_gdb.os.path, "isfile", return_value=isfile)
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            try:
                rc = openocd_gdb.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue(), cleanup_calls


class GdbMoreTests(unittest.TestCase):
    def test_gdb_not_found(self):
        rc, _, err, _ = _run(["backtrace"], isfile=False)
        self.assertEqual(rc, 1)
        self.assertIn("arm-none-eabi-gdb 不存在", err)

    def test_invalid_gdb_commands(self):
        rc, _, err, _ = _run(
            ["frame", "--expr", "1"], build_cmds_exc=ValueError("bad action"))
        self.assertEqual(rc, 1)
        self.assertIn("bad action", err)

    def test_server_start_failure_still_cleans_up(self):
        calls = []
        rc, _, _, _ = _run(["server"], start_exc=FileNotFoundError(),
                           cleanup_calls=calls)
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 1)

    def test_server_ready_skips_cleanup(self):
        calls = []
        rc, _, _, _ = _run(["server"], cleanup_calls=calls)
        self.assertIsNone(rc)
        self.assertEqual(calls, [])

    def test_run_command_cleanup_runs(self):
        calls = []
        rc, _, _, _ = _run(["run", "--commands", "info registers"], cleanup_calls=calls)
        self.assertIsNone(rc)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
