r"""F-244: openocd_telnet main 的校验链与错误出口补测。

## 覆盖对象

`scripts/openocd_telnet.py` 此前 84% 覆盖（2026-11-02 实测）：main() 的
端口非整数 / 配置缺失 / 地址缺失 / 值缺失 / 非法地址 / 服务未就绪 /
exe 缺失 / telnet 连接失败 / 成功写回共九条路径未执行。

## 夹具

runtime 依赖模块引用替换；`TelnetConnection` / `execute_action` 用假对象，
不启 OpenOCD、不连 TCP。
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

import openocd_telnet  # noqa: E402


class _CaptureOut(io.StringIO):
    def reconfigure(self, **_kwargs):
        pass


def _params(**over):
    base = {"board": "b.cfg", "board_source": "cli",
            "interface": "", "interface_source": "cli",
            "target": "", "target_source": "cli",
            "adapter_speed": "", "adapter_speed_source": "cli",
            "transport": "", "transport_source": "cli"}
    base.update(over)
    return base


def _run_main(argv, *, project_config=None, params=None, ready=(True, []),
              start_exc=None, connect_exc=None, connect_exc_cls=None,
              action_result=None):
    out, err = _CaptureOut(), io.StringIO()
    records = {"config": []}
    project_config = project_config if project_config is not None else {}
    params = params if params is not None else _params()
    action_result = action_result or {"status": "ok", "summary": "done"}

    class _FakeTelnet:
        def __init__(self, **_kw):
            pass

        def connect(self):
            if connect_exc_cls:
                raise connect_exc_cls("refused")

        def close(self):
            pass

    old = sys.argv
    sys.argv = ["openocd_telnet.py", *argv]
    try:
        with ExitStack() as stack:
            def patch(obj, name, **kwargs):
                stack.enter_context(mock.patch.object(obj, name, **kwargs))

            ws = stack.enter_context(tempfile.TemporaryDirectory())
            patch(openocd_telnet, "workspace_root", return_value=ws)
            patch(openocd_telnet, "load_project_config", return_value=project_config)
            patch(openocd_telnet, "load_workspace_state", return_value={})
            patch(openocd_telnet, "build_state_lookup", return_value={})
            patch(openocd_telnet, "resolve_openocd_params", return_value=params)
            patch(openocd_telnet, "resolve_param", return_value=("openocd", "cli"))
            patch(openocd_telnet, "build_openocd_cmd", return_value=["openocd"])
            patch(openocd_telnet, "start_openocd_server",
                  side_effect=start_exc if start_exc else None,
                  return_value=None if start_exc else object())
            patch(openocd_telnet, "wait_server_ready", return_value=ready)
            patch(openocd_telnet, "TelnetConnection", new=_FakeTelnet)
            patch(openocd_telnet, "execute_action", return_value=action_result)
            patch(openocd_telnet, "save_project_config",
                  side_effect=lambda ws, vals: records["config"].append(vals))
            patch(openocd_telnet, "cleanup_proc")
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            try:
                rc = openocd_telnet.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue(), records


class ValidationTests(unittest.TestCase):
    def test_non_integer_ports(self):
        rc, _, err, _ = _run_main(["halt"], project_config={"gdb_port": "abc"})
        self.assertEqual(rc, 1)
        self.assertIn("须为整数", err)

    def test_missing_board_and_target(self):
        rc, _, err, _ = _run_main(
            ["halt"], params=_params(board="", interface="", target=""))
        self.assertEqual(rc, 1)
        self.assertIn("必须提供 --board", err)

    def test_missing_address(self):
        rc, _, err, _ = _run_main(["read-mem"])
        self.assertEqual(rc, 1)
        self.assertIn("必须提供 --address", err)

    def test_missing_value(self):
        rc, _, err, _ = _run_main(["write-mem", "--address", "0x08000000"])
        self.assertEqual(rc, 1)
        self.assertIn("必须提供 --value", err)

    def test_invalid_address(self):
        rc, _, err, _ = _run_main(["read-mem", "--address", "134217726"])
        self.assertEqual(rc, 1)
        self.assertIn("地址须为 0x 前缀", err)


class RuntimeErrorTests(unittest.TestCase):
    def test_server_not_ready(self):
        rc, _, err, _ = _run_main(["halt"], ready=(False, ["boom"]))
        self.assertEqual(rc, 1)
        self.assertIn("boom", err)

    def test_openocd_missing(self):
        rc, _, err, _ = _run_main(["halt"], start_exc=FileNotFoundError())
        self.assertEqual(rc, 1)
        self.assertIn("openocd 不存在", err)

    def test_telnet_connect_failed(self):
        rc, out, _, _ = _run_main(["halt", "--json"], connect_exc_cls=ConnectionError)
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["error"]["code"], "telnet_connect_failed")


class SuccessTests(unittest.TestCase):
    def test_success_persists_config_json(self):
        rc, out, _, records = _run_main(["halt", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["status"], "ok")
        self.assertEqual(records["config"][0]["board"], "b.cfg")

    def test_success_text_output(self):
        rc, out, _, _ = _run_main(["halt"])
        self.assertIsNone(rc)
        self.assertIn("[halt]", out)

    def test_error_result_exit_one(self):
        rc, out, _, records = _run_main(
            ["halt", "--json"], action_result={"status": "error",
                                               "error": {"message": "nope"}})
        self.assertEqual(rc, 1)
        self.assertIn("nope", out)
        self.assertEqual(records["config"], [])


if __name__ == "__main__":
    unittest.main()
