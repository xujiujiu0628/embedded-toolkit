r"""serial_mux 生命周期回归钉 (F-097, WB-A / 审计 P1-3)。

缺陷: start_mux 的 wait_for_tcp_server 失败分支直接 return, 不 terminate
已启动的 p1 (serve 进程) → 孤儿进程独占真实串口且无台账; _serial_read_loop
异常静默 set stop_event → serve 死因零留痕 (父进程早已返回成功)。

修复后契约:
  1. 服务起不来 → p1 被 terminate (无孤儿)
  2. 读循环死亡 → stderr 留痕 + %TEMP%/serial_mux/serve_<port>.failed 现场
  3. 异常路径统一回收 _mux_procs

测试不依赖真串口/socat: p1 用**解释器自身的长睡进程**做占位 (不起 TCP、
也不 open serial), 故零外部命令依赖。

F-182 (WB-20260921-03 / GAP-ENV-3): 旧版在用例开头按
`shutil.which("sleep")` 守卫, PATH 无 coreutils 时整例**静默 skip** ——
"全绿"口径随 PATH 在 skipped 7↔6 间漂移而不自知。占位进程既已由解释器
自身承担 (与外部 `sleep` 无关), 该守卫已无存在理由, **删除**;
skip 数自此与 PATH 无关 (收单口径: 全量 skipped 恒 6)。
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

# F-182: 占位进程用解释器自身长睡 —— 零外部命令依赖 (旧版依赖外部 `sleep`)
_PLACEHOLDER_CODE = "import time; time.sleep(60)"

# 注意: 下面的用例用 `mock.patch.object(serial_mux.subprocess, "Popen", …)` ——
# 而 `serial_mux.subprocess` 就是全局 subprocess 模块 (GAP-ENV-1 同族, 见 GAP-F-9),
# 故必须在 import 期先抓住真实句柄, 否则占位进程会递归调回 fake。
_REAL_POPEN = subprocess.Popen


def _spawn_placeholder(**kw):
    return _REAL_POPEN([sys.executable, "-c", _PLACEHOLDER_CODE], **kw)


def _reap(proc):
    """收尾: terminate → 超时兜底 kill, 不留孤儿 (F-182 §4.7)。"""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


class MuxStartNoLeakTests(unittest.TestCase):
    """修复钉 1: 服务起不来时 p1 必须被回收"""

    def test_failed_start_terminates_p1(self):
        # 假 serve: 起一个长睡进程 → wait_for_tcp_server 被 monkeypatch 成
        # False (poll 恒 None → 超时 False), 模拟"进程起了但服务没起"的窗口。
        # F-182: 占位进程由解释器自身承担, 无外部 `sleep` 依赖, 无 skip 守卫。
        calls = {}

        def fake_popen(cmd, **kw):
            p = _spawn_placeholder(**kw)
            self.addCleanup(_reap, p)
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
    """修复钉 2: 读循环死亡必须留痕 + 非零退出。
    F-159: 端口 29876/29877 硬编码 → 动态空闲口; 全局 tempdir 死亡标记
    setUp 先清 (跨运行残留会假绿/假红)。"""

    def setUp(self):
        self.tcp_port = serial_mux.find_free_port()
        self.marker = os.path.join(tempfile.gettempdir(), "serial_mux",
                                   f"serve_{self.tcp_port}.failed")
        if os.path.exists(self.marker):
            os.remove(self.marker)
        self.addCleanup(lambda: os.path.exists(self.marker)
                        and os.remove(self.marker))

    def _server(self):
        return serial_mux.SerialMuxServer(
            {"port": "X", "baudrate": 115200, "bytesize": 8,
             "parity": "none", "stopbits": 1}, tcp_port=self.tcp_port)

    def test_read_loop_death_writes_failure_marker(self):
        server = self._server()
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
        self.assertTrue(os.path.exists(self.marker),
                        f"死亡现场未落盘: {self.marker}")
        content = open(self.marker, encoding="utf-8").read()
        self.assertIn("device disconnected", content)

    def test_normal_stop_does_not_exit_1(self):
        """stop_event 置位 (正常关闭) 不触发死亡路径"""
        server = self._server()
        class _Quiet:
            in_waiting = 0
            def read(self, n):
                time.sleep(0.05)
                return b""
        server.serial_port = _Quiet()
        server.server_sock = mock.Mock()
        server.stop_event.set()   # 先置位 → 循环应直接退出, 不走死亡分支
        server._serial_read_loop()   # 不应 os._exit
        self.assertFalse(os.path.exists(self.marker))


if __name__ == "__main__":
    unittest.main()
