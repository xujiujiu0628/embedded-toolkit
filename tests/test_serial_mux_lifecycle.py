r"""serial_mux 生命周期回归钉 (F-097, WB-A / 审计 P1-3)。

缺陷: start_mux 的 wait_for_tcp_server 失败分支直接 return, 不 terminate
已启动的 p1 (serve 进程) → 孤儿进程独占真实串口且无台账; _serial_read_loop
异常静默 set stop_event → serve 死因零留痕 (父进程早已返回成功)。

修复后契约:
  1. 服务起不来 → p1 被 terminate (无孤儿)
  2. 读循环死亡 → stderr 留痕 + %TEMP%/serial_mux/serve_<port>.failed 现场
  3. 异常路径统一回收 _mux_procs

测试不依赖真串口/socat: p1 用假 serve 脚本 (起 TCP 但永不 open serial)。
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_mux  # noqa: E402


class MuxStartNoLeakTests(unittest.TestCase):
    """修复钉 1: 服务起不来时 p1 必须被回收"""

    def test_failed_start_terminates_p1(self):
        # 假 serve: 起一个进程但立刻退出 → wait_for_tcp_server 返回 False
        # (用 sleep 进程模拟"启动了但没起服务"的窗口, poll 恒 None → 超时 False)
        if os.name != "posix" and shutil.which("sleep") is None:
            self.skipTest("无 sleep 模拟进程")
        calls = {"terminated": []}

        real_popen = subprocess.Popen

        def fake_popen(cmd, **kw):
            p = real_popen([sys.executable, "-c",
                            "import time; time.sleep(30)"], **kw)
            self.addCleanup(p.kill)
            calls["p1"] = p
            return p

        def fake_wait(port, proc, timeout=2.0):
            return False   # 模拟服务起不来

        with mock.patch.object(serial_mux.subprocess, "Popen", fake_popen), \
             mock.patch.object(serial_mux, "wait_for_tcp_server", fake_wait), \
             mock.patch.object(serial_mux.shutil, "which", lambda x: "/usr/bin/socat"):
            out = serial_mux.start_mux(port="COMX", baudrate=115200,
                                       workspace=None,
                                       vserial_link="/tmp/nonexistent_link")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"]["code"], "port_open_failed")
        # 核心断言: p1 必须已被 terminate (旧版漏报点)
        self.assertIn("p1", calls)
        self.assertIsNotNone(calls["p1"].poll(),
                             "p1 应在失败分支被 terminate (旧版泄漏)")


class ReadLoopDeathTraceTests(unittest.TestCase):
    """修复钉 2: 读循环死亡必须留痕 + 非零退出"""

    def test_read_loop_death_writes_failure_marker(self):
        server = serial_mux.SerialMuxServer(
            {"port": "X", "baudrate": 115200, "bytesize": 8,
             "parity": "none", "stopbits": 1}, tcp_port=29876)
        # 伪造 serial_port: read 抛异常 → 读循环死亡
        class _Boom:
            in_waiting = 0
            def read(self, n):
                raise RuntimeError("device disconnected")
        server.serial_port = _Boom()
        server.server_sock = mock.Mock()

        # serve 子进程内 run() 的主循环逻辑: 读循环死亡 → stop_event + os._exit(1)
        # 这里直接调 _serial_read_loop 并捕获 os._exit
        with mock.patch.object(serial_mux.os, "_exit",
                               side_effect=SystemExit(1)) as m_exit:
            with self.assertRaises(SystemExit):
                server._serial_read_loop()
        self.assertEqual(m_exit.call_args[0][0], 1,
                         "读循环死亡必须非零退出 (旧版静默 break)")
        marker = os.path.join(tempfile.gettempdir(), "serial_mux",
                              "serve_29876.failed")
        self.assertTrue(os.path.exists(marker),
                        f"死亡现场未落盘: {marker}")
        content = open(marker, encoding="utf-8").read()
        self.assertIn("device disconnected", content)
        os.remove(marker)

    def test_normal_stop_does_not_exit_1(self):
        """stop_event 置位 (正常关闭) 不触发死亡路径"""
        server = serial_mux.SerialMuxServer(
            {"port": "X", "baudrate": 115200, "bytesize": 8,
             "parity": "none", "stopbits": 1}, tcp_port=29877)
        class _Quiet:
            in_waiting = 0
            def read(self, n):
                time.sleep(0.05)
                return b""
        server.serial_port = _Quiet()
        server.server_sock = mock.Mock()
        server.stop_event.set()   # 先置位 → 循环应直接退出, 不走死亡分支
        server._serial_read_loop()   # 不应 os._exit
        marker = os.path.join(tempfile.gettempdir(), "serial_mux",
                              "serve_29877.failed")
        self.assertFalse(os.path.exists(marker))


import shutil  # noqa: E402
import time  # noqa: E402

if __name__ == "__main__":
    unittest.main()
