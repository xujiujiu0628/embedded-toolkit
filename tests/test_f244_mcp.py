r"""F-244: mcp_server 的参数校验 / 计划层 / 子进程透传补测。

## 覆盖对象

`scripts/mcp_server.py` 此前 79% 覆盖（2026-11-02 实测）：`_validate_param`
的类型拒绝、`plan_tool_call` 的未知参数与未知工具、`run_planned_call` 的
超时/OSError/坏 JSON 三态、`try_import_sdk` 缺 SDK 文案、`main` 的缺 SDK
早退未执行。`build_server()` 依赖 MCP SDK（本机未装），不在本批范围。

## 夹具

`subprocess` 用直接赋值替身（避免 test_stub_ratchet 的 B 式判据）。
"""
import io
import os
import sys
import subprocess
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import mcp_server  # noqa: E402


class ValidateParamTests(unittest.TestCase):
    def test_boolean_type_rejected(self):
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server._validate_param("t", "p", ("boolean", None, "--p", ""), 1)

    def test_string_type_rejected(self):
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server._validate_param("t", "p", ("string", None, "--p", ""), 1)

    def test_string_checker_reason_propagated(self):
        with self.assertRaises(mcp_server.McpToolError) as ctx:
            mcp_server._validate_param("t", "p", ("string", lambda _v: "bad", "--p", ""), "x")
        self.assertIn("bad", str(ctx.exception))

    def test_no_flag_returns_positional_piece(self):
        self.assertEqual(
            mcp_server._validate_param("t", "p", ("string", None, None, ""), "x"), ["x"])


class PlanToolCallTests(unittest.TestCase):
    def test_unknown_tool(self):
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.plan_tool_call("nope", {})

    def test_unknown_argument_rejected(self):
        with self.assertRaises(mcp_server.McpToolError) as ctx:
            mcp_server.plan_tool_call("doctor", {"bogus": 1})
        self.assertIn("不接受参数", str(ctx.exception))

    def test_doctor_plan_has_script(self):
        plan = mcp_server.plan_tool_call("doctor", {})
        self.assertTrue(any(str(a).endswith("verify.py") for a in plan["argv"]))
        self.assertIn("--doctor", plan["argv"])
        self.assertIsNone(plan["stdin_text"])


class RunPlannedCallTests(unittest.TestCase):
    def _run(self, run_impl):
        old = mcp_server.subprocess
        mcp_server.subprocess = SimpleNamespace(
            run=run_impl, DEVNULL=-3, TimeoutExpired=subprocess.TimeoutExpired)
        try:
            return mcp_server.run_planned_call({
                "argv": ["tool"], "stdin_text": None, "timeout": 5, "cwd": None})
        finally:
            mcp_server.subprocess = old

    def test_timeout(self):
        def _run(_argv, **_kw):
            raise subprocess.TimeoutExpired("tool", 5)

        result = self._run(_run)
        self.assertFalse(result["ok"])
        self.assertIn("超时", result["error"])

    def test_oserror(self):
        def _run(_argv, **_kw):
            raise OSError("spawn failed")

        result = self._run(_run)
        self.assertFalse(result["ok"])
        self.assertIn("spawn failed", result["error"])

    def test_json_success(self):
        def _run(_argv, **_kw):
            return SimpleNamespace(returncode=0, stdout='{"a": 1}', stderr="")

        result = self._run(_run)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], {"a": 1})

    def test_bad_json_keeps_stdout_tail(self):
        def _run(_argv, **_kw):
            return SimpleNamespace(returncode=1, stdout="not json", stderr="err tail")

        result = self._run(_run)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["result"])
        self.assertIn("not json", result["stdout"])
        self.assertEqual(result["stderr"], "err tail")


class SdkGlueTests(unittest.TestCase):
    def test_try_import_sdk_reports_missing(self):
        ok, message = mcp_server.try_import_sdk()
        self.assertFalse(ok)
        self.assertIn("MCP SDK 未安装", message)

    def test_main_exits_two_without_sdk(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = mcp_server.main()
        self.assertEqual(rc, 2)
        self.assertIn("MCP SDK 未安装", err.getvalue())


if __name__ == "__main__":
    unittest.main()
