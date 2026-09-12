r"""JSON 模式失败退出码契约回归钉 (工单 P0-2, F-120)。

缺陷: 四脚本的 **执行失败** JSON 出口只 output_json 不 exit → 退出码 0;
同文件早段校验失败在 JSON 模式下却 exit(1)——同一契约自相矛盾;
serial_mux main 全程无退出码。

契约 (修复后): 所有 JSON 出口统一 exit(0 if result.status=="ok" else 1)。
进程内 mock 驱动 main(): 假 openocd/假连接覆盖"执行失败"分支 (真机才可达),
断言退出码; 反向钉 ok 路径不得退非 0。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_gdb    # noqa: E402
import openocd_run    # noqa: E402
import openocd_telnet # noqa: E402
import serial_mux     # noqa: E402

ERR = {"status": "error", "error": {"code": "command_failed", "message": "boom"}}


class _ReconfigurableStringIO(io.StringIO):
    """output_json 会 sys.stdout.reconfigure(encoding=...) — StringIO 没有该方法"""

    def reconfigure(self, **kwargs):  # noqa: ARG002
        return None


class _ExitCapture:
    """跑 main() 返回退出码: SystemExit.code, 未退出则 0 (契约违例语义)"""

    def __init__(self, module, argv, workspace, json_flag=True):
        self.module, self.argv, self.ws = module, argv, workspace
        # serial_mux 无 --json 开关 (恒 JSON), 其余三脚本统一带
        self.extra = ["--json", "--workspace", workspace] if json_flag \
            else ["--workspace", workspace]

    def __call__(self):
        buf = _ReconfigurableStringIO()
        code = None
        with mock.patch.object(sys, "argv", [self.module.__name__ + ".py"] + self.argv +
                               self.extra), \
             redirect_stdout(buf):
            try:
                self.module.main()
            except SystemExit as exc:
                code = exc.code if exc.code is not None else 0
        out = buf.getvalue()
        parsed = json.loads(out) if out.strip() else {}
        return code if code is not None else 0, parsed


class OpenocdRunExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = tempfile.mkdtemp(prefix="f120_run_")

    def _main_with(self, fake_run_openocd, argv):
        with mock.patch.object(openocd_run, "run_openocd", return_value=fake_run_openocd):
            cap = _ExitCapture(openocd_run, argv, self.ws)
            return cap()

    def test_exec_failure_json_exits_1(self):
        code, out = self._main_with({**ERR, "action": "erase", "details": {}},
                                    ["erase", "--mode", "mass", "--exe", "no-such"])
        self.assertEqual(out["status"], "error")
        self.assertEqual(code, 1)

    def test_exec_ok_json_exits_0(self):
        ok = {"status": "ok", "action": "erase", "summary": "erased", "details": {}}
        code, out = self._main_with(ok, ["erase", "--mode", "mass", "--exe", "no-such"])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(code, 0)

    def test_missing_file_json_exits_1_reverse(self):
        # 早段校验路径 (原本就 exit 1) 不得回归
        code, out = _ExitCapture(openocd_run,
                                 ["flash", "--file", os.path.join(self.ws, "no.bin"),
                                  "--exe", "x", "--board", "b.cfg"], self.ws)()
        self.assertEqual(out["status"], "error")
        self.assertEqual(code, 1)


class OpenocdGdbExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = tempfile.mkdtemp(prefix="f120_gdb_")

    def test_gdb_exec_failure_json_exits_1(self):
        fake_proc = mock.Mock(pid=4242)
        fake_proc.poll.return_value = None
        with mock.patch.object(openocd_gdb, "start_openocd_server", return_value=fake_proc), \
             mock.patch.object(openocd_gdb, "wait_server_ready", return_value=(True, [])), \
             mock.patch.object(openocd_gdb, "run_gdb_commands",
                               return_value={"status": "error", "error": "gdb died"}), \
             mock.patch.object(openocd_gdb, "cleanup"):
            code, out = _ExitCapture(
                openocd_gdb,
                ["run", "--commands", "bt", "--board", "b.cfg",
                 "--gdb-exe", sys.executable, "--elf", __file__, "--exe", "x"],
                self.ws)()
        self.assertEqual(out["status"], "error")
        self.assertEqual(code, 1, "gdb 执行失败 + --json 必须退 1")


class OpenocdTelnetExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = tempfile.mkdtemp(prefix="f120_telnet_")

    def _drive(self, action_result):
        fake_proc = mock.Mock(pid=4242)
        fake_proc.poll.return_value = None
        with mock.patch.object(openocd_telnet, "start_openocd_server", return_value=fake_proc), \
             mock.patch.object(openocd_telnet, "wait_server_ready", return_value=(True, [])), \
             mock.patch.object(openocd_telnet, "TelnetConnection"), \
             mock.patch.object(openocd_telnet, "execute_action", return_value=action_result), \
             mock.patch.object(openocd_telnet, "cleanup_proc"):
            return _ExitCapture(openocd_telnet,
                                ["halt", "--board", "b.cfg", "--exe", "x"], self.ws)()

    def test_action_failure_json_exits_1(self):
        code, out = self._drive({**ERR, "action": "halt"})
        self.assertEqual(out["status"], "error")
        self.assertEqual(code, 1)

    def test_action_ok_json_exits_0(self):
        code, out = self._drive({"status": "ok", "action": "halt",
                                 "summary": "halted", "details": {}})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(code, 0)


class SerialMuxExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = tempfile.mkdtemp(prefix="f120_mux_")

    def test_start_failure_exits_1(self):
        # socat 缺失路径 → error result (Windows 本机天然无 socat, mock 固化两平台一致)
        with mock.patch.object(serial_mux.shutil, "which", return_value=None):
            code, out = _ExitCapture(serial_mux,
                                     ["start", "--port", "COM9"], self.ws,
                                     json_flag=False)()
        self.assertEqual(out["status"], "error")
        self.assertEqual(code, 1, "mux start 失败必须退 1 (旧版全程无退出码)")

    def test_status_not_running_exits_0(self):
        code, out = _ExitCapture(serial_mux, ["status"], self.ws,
                                 json_flag=False)()
        self.assertEqual(out["status"], "ok")   # "未运行"是成功查询
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
