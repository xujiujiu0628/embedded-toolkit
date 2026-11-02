r"""F-240: openocd_gdb 的 legacy 模式、gdb_exe 解析与文本输出补测。

## 覆盖对象

`scripts/openocd_gdb.py` 此前 76% 覆盖（2026-11-02 实测）：`build_parser`
的 legacy 分支、`_legacy_mode` 走 main 的路径、gdb_exe 的三级解析
（CLI → project_config → PATH → 缺失）、run 子命令、文本输出与
FileNotFoundError 出口未执行。

## 夹具

runtime 依赖模块引用替换；gdb_exe 用临时文件冒充可执行路径；不启真进程。
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
    pid = 99

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


def _run_main(argv, *, project_config=None, which_ret=None, gdb_result=None,
              start_exc=None, no_gdb_exe=False):
    out, err = io.StringIO(), io.StringIO()
    records = {"gdb_calls": []}
    gdb_exe = os.path.join(tempfile.gettempdir(), "fake-gdb.exe")
    project_config = project_config or {}

    def _rp(name, *_a, **_k):
        if name == "exe":
            return ("openocd", "cli")
        if name == "gdb_exe":
            if no_gdb_exe or "gdb_exe" in project_config:
                return (None, "default")
            return (gdb_exe, "cli")
        if name == "elf":
            return ("fw.elf", "cli")
        return (None, "default")

    def _start(*_a, **_k):
        if start_exc:
            raise start_exc
        return _FakeProc()

    def _run_gdb(exe, elf, remote, commands, timeout=30):
        records["gdb_calls"].append(list(commands))
        return gdb_result or {"status": "ok", "stdout": "", "returncode": 0}

    old_argv = sys.argv
    sys.argv = ["openocd_gdb.py", *argv]
    try:
        with ExitStack() as stack:
            def patch(obj, name, **kwargs):
                stack.enter_context(mock.patch.object(obj, name, **kwargs))

            workspace = stack.enter_context(tempfile.TemporaryDirectory())
            patch(openocd_gdb, "workspace_root", return_value=workspace)
            patch(openocd_gdb, "save_project_config")
            patch(openocd_gdb, "default_config_path", return_value="cfg.json")
            patch(openocd_gdb, "normalize_path", side_effect=str)
            patch(openocd_gdb, "load_json_file", return_value={})
            patch(openocd_gdb, "load_workspace_state", return_value={})
            patch(openocd_gdb, "_state_lookup", return_value={})
            patch(openocd_gdb, "load_project_config", return_value=project_config)
            patch(openocd_gdb, "resolve_openocd_params", return_value=_params())
            patch(openocd_gdb, "resolve_param", side_effect=_rp)
            patch(openocd_gdb, "which", return_value=which_ret)
            patch(openocd_gdb, "build_openocd_cmd", return_value=["openocd"])
            patch(openocd_gdb, "start_openocd_server", side_effect=_start)
            patch(openocd_gdb, "wait_server_ready", return_value=(True, []))
            patch(openocd_gdb, "update_state_entry", return_value={})
            patch(openocd_gdb, "run_gdb_commands", side_effect=_run_gdb)
            patch(openocd_gdb, "cleanup")
            patch(openocd_gdb.os.path, "isfile", return_value=True)
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            try:
                rc = openocd_gdb.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old_argv
    return rc, out.getvalue(), err.getvalue(), records


class LegacyModeTests(unittest.TestCase):
    def test_legacy_parser_has_no_command(self):
        parser = openocd_gdb.build_parser(legacy_server=True)
        args = parser.parse_args(["--exe", "openocd"])
        self.assertFalse(hasattr(args, "command"))

    def test_legacy_main_runs_server(self):
        rc, out, _, _ = _run_main([])
        self.assertIsNone(rc)
        self.assertIn("GDB Server 已就绪", out)

    def test_server_text_output(self):
        rc, out, _, _ = _run_main(["server"])
        self.assertIsNone(rc)
        self.assertIn("PID: 99", out)


class GdbExeResolutionTests(unittest.TestCase):
    def test_project_config_gdb_exe_used(self):
        rc, out, _, records = _run_main(
            ["backtrace", "--json"],
            project_config={"gdb_exe": "/proj/gdb"},
            which_ret=None)
        self.assertEqual(rc, 0)
        self.assertEqual(records["gdb_calls"][0], ["monitor halt", "backtrace"])

    def test_path_discovery_used(self):
        rc, _, _, records = _run_main(
            ["backtrace", "--json"], which_ret="/usr/bin/arm-none-eabi-gdb")
        self.assertEqual(rc, 0)
        self.assertTrue(records["gdb_calls"])

    def test_missing_gdb_exe_exits_one(self):
        rc, _, err, _ = _run_main(["backtrace"], which_ret=None, no_gdb_exe=True)
        self.assertEqual(rc, 1)
        self.assertIn("gdb_exe", err)


class RunCommandTests(unittest.TestCase):
    def test_run_passes_explicit_commands(self):
        rc, _, _, records = _run_main(
            ["run", "--commands", "info registers", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(records["gdb_calls"][0], ["info registers"])

    def test_non_json_success_prints_output(self):
        result = {"status": "ok", "stdout": "frame output\n", "returncode": 0}
        rc, out, _, _ = _run_main(["backtrace"], gdb_result=result)
        self.assertIsNone(rc)
        self.assertIn("[gdb-backtrace]", out)
        self.assertIn("frame output", out)


class ExeNotFoundTests(unittest.TestCase):
    def test_openocd_missing_exits_one(self):
        rc, _, err, _ = _run_main(["backtrace"], start_exc=FileNotFoundError())
        self.assertEqual(rc, 1)
        self.assertIn("openocd 不存在", err)


if __name__ == "__main__":
    unittest.main()
