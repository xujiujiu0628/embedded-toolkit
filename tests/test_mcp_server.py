r"""F-130 (工单二 A-3) MCP server 回归钉。

契约:
  1. 注册表单一数据结构, 且每个工具映射的脚本真实存在 (防注册表腐烂);
  2. 入参白名单: 未知参数拒绝、值以 "-" 开头拒绝 (flag 注入)、越界拒绝;
  3. 工程根校验: 不存在 / 缺 .workbench/config.json 一律拒绝 (不给
     文件系统探测面, agentic-hil 安全设计);
  4. 分发 = 纯计划层 (plan_tool_call) + 子进程透传 (run_planned_call),
     mock 子进程层测工具分发与错误透传 (F-120: 失败退出码非零 → ok=False);
  5. diagnose_hardfault 只解析不探针: 走 hardfault.py --no-probe,
     MCP 层不触硬件, hardfault --no-probe 自身路径有专项测试。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hardfault  # noqa: E402
import mcp_server  # noqa: E402


class RegistryIntegrityTests(unittest.TestCase):
    """验收: 工具一节注册表与脚本路径的映射钉死"""

    def test_every_tool_script_exists(self):
        for name, tool in mcp_server._TOOL_REGISTRY.items():
            path = mcp_server._script_path(tool)
            self.assertTrue(os.path.isfile(path),
                            f"工具 {name} 映射的脚本不存在: {path}")

    def test_workorder_six_tools_registered(self):
        # 工单 A-3 点名六工具, 注册表少一个即红
        self.assertEqual(
            set(mcp_server._TOOL_REGISTRY),
            {"run_verify", "lint_expectations", "gen_peripheral",
             "rm_lookup", "diagnose_hardfault", "doctor"})

    def test_schema_generated_from_registry(self):
        schema = mcp_server.tool_input_schema("run_verify")
        self.assertEqual(schema["type"], "object")
        self.assertIn("project", schema["properties"])
        self.assertIn("timeout", schema["properties"])
        self.assertIn("project", schema["required"])
        # gen_peripheral 的必填 type 进 required
        gen_schema = mcp_server.tool_input_schema("gen_peripheral")
        self.assertNotIn("project", gen_schema["required"])
        self.assertIn("type", gen_schema["required"])


class ProjectGuardTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"))
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_valid_project_resolves_abs(self):
        ws = mcp_server.resolve_project(self.ws)
        self.assertTrue(os.path.isabs(ws))

    def test_missing_dir_rejected(self):
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.resolve_project(os.path.join(self.ws, "nope"))

    def test_non_project_dir_rejected(self):
        # 传工具库自身路径/任意空目录 → 拒绝 (不给文件系统探测面)
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.resolve_project(tempfile.mkdtemp())

    def test_empty_project_rejected(self):
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.resolve_project("  ")


class ParamWhitelistTests(unittest.TestCase):
    """不给 agent 任意 shell: 未知键 / flag 注入 / 越界 全拒绝"""

    def test_unknown_param_rejected(self):
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.plan_tool_call("run_verify", {"shell": "rm -rf /"})

    def test_unknown_tool_rejected(self):
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.plan_tool_call("exec", {"cmd": "anything"})

    def test_flag_injection_rejected(self):
        # 查询词以 "-" 开头 = 注入 CLI 旗标, 白名单层拒绝
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.plan_tool_call("rm_lookup", {"query": "--raw"})
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.plan_tool_call("rm_lookup", {"recipe": "-x y"})

    def test_gen_periph_bounds(self):
        for bad in ({"ch": 25}, {"duty": 140}, {"freq": 0},
                    {"type": "gpio; rm"}, {"pin": "PA0; ls"}):
            with self.assertRaises(mcp_server.McpToolError, msg=bad):
                mcp_server.plan_tool_call(
                    "gen_peripheral", dict({"type": "pwm"}, **bad))

    def test_missing_required_param_rejected(self):
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.plan_tool_call("gen_peripheral", {"pin": "PA0"})
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.plan_tool_call("diagnose_hardfault", {})

    def test_integer_type_confusion_rejected(self):
        # bool 是 int 子类 — 显式拒绝 (True 不得冒充 ch=1)
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.plan_tool_call("gen_peripheral",
                                      {"type": "adc", "ch": True})


class DispatchPlanTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"))
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_run_verify_plan(self):
        plan = mcp_server.plan_tool_call(
            "run_verify", {"project": self.ws, "timeout": 15,
                           "no_flash": True})
        argv = plan["argv"]
        self.assertTrue(argv[0].endswith("python.exe")
                        or argv[0] == sys.executable)
        self.assertTrue(argv[1].endswith("verify.py"))
        self.assertIn("--json", argv)
        self.assertIn("--timeout", argv)
        self.assertEqual(argv[argv.index("--timeout") + 1], 15)
        self.assertIn("--no-flash", argv)
        self.assertEqual(plan["cwd"], os.path.abspath(self.ws))

    def test_doctor_needs_no_project(self):
        plan = mcp_server.plan_tool_call("doctor", {})
        self.assertIsNone(plan["cwd"])
        self.assertIn("--doctor", plan["argv"])

    def test_diagnose_hardfault_goes_via_stdin(self):
        # 仅解析不探针: --no-probe + --fault-text -, 文本走 stdin
        plan = mcp_server.plan_tool_call(
            "diagnose_hardfault", {"text": "[HF] PC=080001CC LR=080002F1"})
        argv = plan["argv"]
        self.assertIn("--no-probe", argv)
        self.assertEqual(
            argv[argv.index("--fault-text") + 1], "-")
        self.assertEqual(plan["stdin_text"],
                         "[HF] PC=080001CC LR=080002F1")
        self.assertTrue(argv[1].endswith("hardfault.py"))

    def test_oversized_stdin_rejected(self):
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.plan_tool_call(
                "diagnose_hardfault", {"text": "x" * 20_001})


class BooleanFlagArgvTests(unittest.TestCase):
    """F-178 (WB-20260920-04, H-1): boolean 参数是 store_true 开关旗标。

    第一层病: `_validate_param` 末行对 False 也成立 (False != "" 恒真),
    argv 里落进裸 Python bool → Windows 上 subprocess.list2cmdline 抛
    `TypeError: expected str, bytes or os.PathLike object, not bool`,
    进程未起且异常不被信封捕获 (违反本文件"统一信封"设计)。
    第二层病: 即便子进程起得来, argparse 的 store_true 旗标带值会报
    `unrecognized arguments`。两层都坏 → run_verify 的两个布尔能力全废。
    """

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"))
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _argv(self, **params):
        return mcp_server.plan_tool_call(
            "run_verify", dict({"project": self.ws}, **params))["argv"]

    def test_true_emits_bare_flag_exactly_once(self):
        argv = self._argv(no_flash=True)
        self.assertEqual(argv.count("--no-flash"), 1, argv)
        self.assertFalse([a for a in argv if isinstance(a, bool)],
                         f"argv 不得含裸 bool: {argv}")
        # 旗标之后不得跟值 (store_true 不接受值)
        idx = argv.index("--no-flash")
        self.assertTrue(idx == len(argv) - 1 or argv[idx + 1].startswith("-"),
                        f"--no-flash 后不得跟值: {argv}")

    def test_false_emits_no_flag_at_all(self):
        argv = self._argv(no_flash=False)
        self.assertNotIn("--no-flash", argv, argv)
        self.assertFalse([a for a in argv if isinstance(a, bool)],
                         f"argv 不得含裸 bool: {argv}")

    def test_require_tgl_same_shape(self):
        # 同族第二个 boolean 一并钉: 修一处漏一处即红
        argv_t = self._argv(require_tgl=True)
        self.assertEqual(argv_t.count("--require-tgl"), 1, argv_t)
        self.assertFalse([a for a in argv_t if isinstance(a, bool)], argv_t)
        argv_f = self._argv(require_tgl=False)
        self.assertNotIn("--require-tgl", argv_f, argv_f)

    def test_boolean_argv_entries_are_all_str(self):
        # 端到端前置: boolean 面产出的 argv 必须全部是 str, 否则
        # subprocess.list2cmdline 在任何平台上都会 TypeError。
        # (True/False 双值都过一遍, 顺序敏感的组合也过)
        # 注: 整数参数 (run_verify.timeout / gen_peripheral 的 ch/freq/duty/
        # baud/speed) 同源地把裸 int 塞进 argv —— 那是另一笔登记缺陷
        # (GAP-F-1, 本单白名单外, 只列不改), 故此处不越界断言整数面。
        for params in ({"no_flash": True, "require_tgl": False},
                       {"no_flash": False, "require_tgl": True}):
            argv = self._argv(**params)
            self.assertTrue(all(isinstance(a, str) for a in argv),
                            f"非 str 元素: {argv}")


class RunPlannedCallTests(unittest.TestCase):
    """mock 子进程层: 分发与错误透传"""

    def _plan(self, **kw):
        base = {"argv": [sys.executable, "tool.py"], "stdin_text": None,
                "cwd": None, "timeout": 30}
        base.update(kw)
        return base

    def test_ok_json_parsed(self):
        with mock.patch.object(mcp_server.subprocess, "run") as m_run:
            m_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({"status": "ok"}), stderr="")
            out = mcp_server.run_planned_call(self._plan())
        self.assertTrue(out["ok"])
        self.assertEqual(out["exit_code"], 0)
        self.assertEqual(out["result"], {"status": "ok"})
        self.assertEqual(m_run.call_args.kwargs.get("input"), None)

    def test_failure_exit_code_passthrough(self):
        # F-120 后 JSON 模式失败退出码非零 — MCP 层如实 ok=False, JSON 仍透传
        with mock.patch.object(mcp_server.subprocess, "run") as m_run:
            m_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1,
                stdout=json.dumps({"status": "fail"}), stderr="boom")
            out = mcp_server.run_planned_call(self._plan())
        self.assertFalse(out["ok"])
        self.assertEqual(out["result"], {"status": "fail"})
        self.assertIn("boom", out["stderr"])

    def test_non_json_stdout_passthrough(self):
        with mock.patch.object(mcp_server.subprocess, "run") as m_run:
            m_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="plain text", stderr="")
            out = mcp_server.run_planned_call(self._plan())
        self.assertTrue(out["ok"])
        self.assertIsNone(out["result"])
        self.assertEqual(out["stdout"], "plain text")

    def test_timeout_is_error_not_raise(self):
        with mock.patch.object(mcp_server.subprocess, "run") as m_run:
            m_run.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=30)
            out = mcp_server.run_planned_call(self._plan())
        self.assertFalse(out["ok"])
        self.assertIn("超时", out["error"])


class SdkMissingMessageTests(unittest.TestCase):
    def test_missing_sdk_gives_actionable_message(self):
        with mock.patch.dict(sys.modules, {"mcp": None}):
            ok, msg = mcp_server.try_import_sdk()
        self.assertFalse(ok)
        self.assertIn("requirements-mcp.txt", msg)

    def test_registry_docstring_example_file_exists(self):
        # 模板入库惯例 (同 machine.example.json)
        self.assertTrue(os.path.isfile(
            os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), ".mcp.json.example")))


class HardfaultNoProbeTests(unittest.TestCase):
    """--no-probe 仅解析通道: 不触 OpenOCD, 层 1 现场行 → fault_site"""

    def _run_main(self, argv, stdin_text=""):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin_text)), \
                mock.patch.object(hardfault, "run_openocd_diag") as m_probe:
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    hardfault.main()
                    code = None
                except SystemExit as e:
                    code = e.code
        return code, out.getvalue(), err.getvalue(), m_probe

    def test_no_probe_never_touches_openocd(self):
        # 安全钉: --no-probe 路径绝不允许调 run_openocd_diag
        code, out, _err, m_probe = self._run_main(
            ["hardfault.py", "--json", "--no-probe", "--fault-text", "-"],
            stdin_text="=== capture ===\n[HF] PC=080001CC LR=080002F1\n")
        m_probe.assert_not_called()
        result = json.loads(out)
        self.assertEqual(result["status"], "parsed_text_only")
        self.assertEqual(result["fault_site"]["pc"], "0x080001CC")
        self.assertEqual(code, 0)

    def test_no_probe_without_marker_is_no_fault(self):
        code, out, _err, m_probe = self._run_main(
            ["hardfault.py", "--json", "--no-probe", "--fault-text", "-"],
            stdin_text="LED ON\nTGL 3\n")
        m_probe.assert_not_called()
        result = json.loads(out)
        self.assertEqual(result["status"], "no_fault_marker")
        self.assertEqual(code, 1)

    def test_no_probe_requires_fault_text(self):
        code, out, _err, m_probe = self._run_main(
            ["hardfault.py", "--json", "--no-probe"])
        m_probe.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("--fault-text", out)


if __name__ == "__main__":
    unittest.main()
