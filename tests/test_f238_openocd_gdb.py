r"""F-238: openocd_gdb 主流程与纯辅助函数补测。

## 覆盖对象

`scripts/openocd_gdb.py` 此前 58% 覆盖（2026-11-02 实测）：`main()` 的参数
解析错误面、server 就绪面与 one-shot 命令执行面未执行。

## 夹具

runtime 依赖全部模块引用替换；server 用假进程（pid/wait），one-shot 用假
GDB 输出。不接真探针、不启真 OpenOCD。
"""
import io
import json
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
    pid = 4321

    def wait(self):
        return 0

    def poll(self):
        return 0


def _params(**overrides):
    base = {
        "board": "b.cfg", "board_source": "cli",
        "interface": "", "interface_source": "cli",
        "target": "", "target_source": "cli",
        "adapter_speed": "", "adapter_speed_source": "cli",
        "transport": "", "transport_source": "cli",
    }
    base.update(overrides)
    return base


def _run_main(argv, *, params=None, resolve_param=None, ready=(True, []),
              gdb_result=None, start_exc=None):
    out, err = io.StringIO(), io.StringIO()
    records = {"state": []}
    gdb_exe = os.path.join(tempfile.gettempdir(), "fake-gdb.exe")

    def _rp(name, *_a, **_k):
        if resolve_param:
            return resolve_param(name)
        if name == "exe":
            return ("openocd", "cli")
        if name == "gdb_exe":
            return (gdb_exe, "cli")
        if name == "elf":
            return ("fw.elf", "cli")
        return (None, "default")

    def _start(*_a, **_k):
        if start_exc:
            raise start_exc
        return _FakeProc()

    old_argv = sys.argv
    sys.argv = ["openocd_gdb.py", *argv]
    try:
        with ExitStack() as stack:
            def patch(obj, name, **kwargs):
                stack.enter_context(mock.patch.object(obj, name, **kwargs))

            # 独立 workspace：绝不能指 tempfile.gettempdir() —— 成功路径会
            # 调 save_project_config 在 workspace 下建 .workbench/，写进系统
            # 临时根会污染其他"无工程根"用例（2026-11-02 实锤）。
            workspace = stack.enter_context(tempfile.TemporaryDirectory())
            patch(openocd_gdb, "workspace_root", return_value=workspace)
            patch(openocd_gdb, "save_project_config")
            patch(openocd_gdb, "default_config_path", return_value="cfg.json")
            patch(openocd_gdb, "normalize_path", side_effect=str)
            patch(openocd_gdb, "load_json_file", return_value={})
            patch(openocd_gdb, "load_workspace_state", return_value={})
            patch(openocd_gdb, "_state_lookup", return_value={})
            patch(openocd_gdb, "load_project_config", return_value={})
            patch(openocd_gdb, "resolve_openocd_params",
                  return_value=params if params is not None else _params())
            patch(openocd_gdb, "resolve_param", side_effect=_rp)
            patch(openocd_gdb, "which", return_value=None)
            patch(openocd_gdb, "build_openocd_cmd", return_value=["openocd"])
            patch(openocd_gdb, "start_openocd_server", side_effect=_start)
            patch(openocd_gdb, "wait_server_ready", return_value=ready)
            patch(openocd_gdb, "update_state_entry",
                  side_effect=lambda *a, **k: records["state"].append(a) or {})
            patch(openocd_gdb, "run_gdb_commands",
                  return_value=gdb_result or {"status": "ok", "stdout": "", "returncode": 0})
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


class HelperTests(unittest.TestCase):
    def test_summary_per_command(self):
        self.assertEqual(openocd_gdb._summary("server", {}), "gdb server 已就绪")
        self.assertIn("frames=1", openocd_gdb._summary("backtrace", {"frames": [1]}))
        self.assertIn("variables=2", openocd_gdb._summary("locals", {"variables": {"a": 1, "b": 2}}))
        self.assertIn("threads=1", openocd_gdb._summary("threads", {"threads": [1]}))
        self.assertIn("value=42", openocd_gdb._summary("print", {"value": "42"}))
        self.assertEqual(openocd_gdb._summary("step", {}), "gdb step 完成")

    def test_metrics_counts_every_section(self):
        metrics = openocd_gdb._metrics({
            "frames": [1, 2], "variables": {"a": 1}, "registers": {"r0": "1"},
            "threads": [1], "disassembly": [1, 2, 3],
        })
        self.assertEqual(metrics, {"frames": 2, "variables": 1, "registers": 1,
                                   "threads": 1, "instructions": 3})

    def test_legacy_mode_detection(self):
        old = sys.argv
        try:
            sys.argv = ["x"]
            self.assertTrue(openocd_gdb._legacy_mode())
            sys.argv = ["x", "backtrace"]
            self.assertFalse(openocd_gdb._legacy_mode())
        finally:
            sys.argv = old

    def test_parser_accepts_actions(self):
        parser = openocd_gdb.build_parser(legacy_server=False)
        args = parser.parse_args(["backtrace"])
        self.assertEqual(args.command, "backtrace")


class MainErrorTests(unittest.TestCase):
    def test_missing_param_exits_one(self):
        def _raise(name):
            raise ValueError("exe 缺失")

        rc, _, err, _ = _run_main(["backtrace"], resolve_param=_raise)
        self.assertEqual(rc, 1)
        self.assertIn("exe 缺失", err)

    def test_missing_config_exits_one(self):
        rc, _, err, _ = _run_main(
            ["backtrace"], params=_params(board="", interface="", target=""))
        self.assertEqual(rc, 1)
        self.assertIn("必须提供", err)

    def test_missing_gdb_exe_exits_one(self):
        def _rp(name):
            if name == "exe":
                return ("openocd", "cli")
            raise ValueError("缺少必要参数: gdb_exe")

        rc, _, err, _ = _run_main(["backtrace"], resolve_param=_rp)
        self.assertEqual(rc, 1)
        self.assertIn("gdb_exe", err)

    def test_server_not_ready_exits_one(self):
        rc, _, err, _ = _run_main(
            ["server"], ready=(False, ["boom"]))
        self.assertEqual(rc, 1)
        self.assertIn("boom", err)
        self.assertIn("失败", err)


class MainSuccessTests(unittest.TestCase):
    def test_server_ready_outputs_ports(self):
        rc, out, _, records = _run_main(["server", "--json"])
        self.assertIsNone(rc)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["details"]["pid"], 4321)
        self.assertEqual(records["state"][0][0], "last_debug")

    def test_backtrace_runs_gdb_and_parses(self):
        result = {"status": "ok", "stdout": "#0  main () at main.c:1\n", "returncode": 0}
        rc, out, _, _ = _run_main(["backtrace", "--json"], gdb_result=result)
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["metrics"]["frames"], 1)

    def test_gdb_error_reported(self):
        result = {"status": "error", "error": "boom"}
        rc, out, _, _ = _run_main(["backtrace", "--json"], gdb_result=result)
        self.assertEqual(rc, 1)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "gdb_error")


if __name__ == "__main__":
    unittest.main()
