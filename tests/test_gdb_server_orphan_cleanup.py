r"""gdb server 模式孤儿进程回归钉 (工单 P0-3, F-121)。

缺陷: openocd_gdb.py finally 只在 `args.command != "server"` 时 cleanup(proc)
——server 模式"启动失败/超时但进程仍活"时 sys.exit(1) 穿过 finally 也不清理,
OpenOCD 留存并独占 ST-Link。修复后契约: ready 未达成 → 必须 cleanup;
只有 ready 成功的常驻 server 才跳过 cleanup (服务进程归调用者管)。

全部 mock, 不碰真机: start_openocd_server/wait_server_ready/cleanup 三钩子。
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

import openocd_gdb  # noqa: E402


class _Buf(io.StringIO):
    def reconfigure(self, **kwargs):
        return None


class ServerOrphanCleanupTests(unittest.TestCase):

    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="f121_gdb_")
        self.proc = mock.Mock(pid=4242)
        self.proc.poll.return_value = None  # 进程"仍活着"

    def _main_server(self, ready, ready_result):
        with mock.patch.object(openocd_gdb, "start_openocd_server",
                               return_value=self.proc), \
             mock.patch.object(openocd_gdb, "wait_server_ready",
                               return_value=ready_result), \
             mock.patch.object(openocd_gdb, "cleanup") as cleanup_mock:
            buf = _Buf()
            code = None
            with mock.patch.object(sys, "argv",
                                   ["openocd_gdb.py", "server", "--board", "b.cfg",
                                    "--exe", "x", "--json", "--workspace", self.ws]), \
                 redirect_stdout(buf):
                try:
                    openocd_gdb.main()
                except SystemExit as exc:
                    code = exc.code
            # ready 成功路径: proc.wait() 在假 proc 上是 Mock, 不阻塞, 直接走完
            # (main 正常 return = 进程 rc 0)
            return (code if code is not None else 0,
                    json.loads(buf.getvalue()) if buf.getvalue().strip() else {},
                    cleanup_mock)

    def test_startup_failure_cleans_up_proc(self):
        """ready 未达成 (超时/失败) → cleanup 必须被调用, 不留孤儿占 ST-Link"""
        code, out, cleanup_mock = self._main_server(
            ready=False, ready_result=(False, ["Error: adapter refused"]))
        self.assertEqual(out["status"], "error")
        self.assertEqual(code, 1)
        cleanup_mock.assert_called_once_with(self.proc)

    def test_ready_server_skips_cleanup(self):
        """ready 成功的常驻 server → finally 不杀服务进程 (正向不回归)"""
        code, out, cleanup_mock = self._main_server(
            ready=True, ready_result=(True, []))
        self.assertEqual(out["status"], "ok")
        self.assertEqual(code, 0)
        cleanup_mock.assert_not_called()

    def test_non_server_failure_still_cleans(self):
        """非 server 模式 ready 失败 → 原有 cleanup 行为零回归"""
        with mock.patch.object(openocd_gdb, "start_openocd_server",
                               return_value=self.proc), \
             mock.patch.object(openocd_gdb, "wait_server_ready",
                               return_value=(False, ["boom"])), \
             mock.patch.object(openocd_gdb, "cleanup") as cleanup_mock:
            buf = _Buf()
            with mock.patch.object(sys, "argv",
                                   ["openocd_gdb.py", "run", "--commands", "bt",
                                    "--board", "b.cfg", "--exe", "x",
                                    "--gdb-exe", sys.executable, "--elf", __file__,
                                    "--json", "--workspace", self.ws]), \
                 redirect_stdout(buf):
                with self.assertRaises(SystemExit):
                    openocd_gdb.main()
        cleanup_mock.assert_called_once_with(self.proc)


if __name__ == "__main__":
    unittest.main()
