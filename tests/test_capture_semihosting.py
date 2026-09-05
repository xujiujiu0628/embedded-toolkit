r"""capture_semihosting 单元测试 (F-061) — 会话与收尸的职责边界钉.

关键契约: 超时时模块只抛 SemihostingTimeout(proc)、**不 kill 不收尸**——
F-003 的回收/归因/exit(1) 全在留守的 _finish_capture_timeout 里。若本模块
自作主张 kill, 调用方的 communicate(5s) 二次回收就拿不到部分输出了。
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import capture_semihosting  # noqa: E402


class _FakeProc:
    def __init__(self, stdout="", stderr="", timeout_exc=None):
        self._stdout, self._stderr = stdout, stderr
        self._timeout_exc = timeout_exc
        self.killed = False
        self.communicate_calls = []

    def communicate(self, timeout=None):
        self.communicate_calls.append(timeout)
        if self._timeout_exc is not None:
            raise self._timeout_exc
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.proc = _FakeProc("LED ON\n", "TGL 3\n")
        self.popen_kwargs = []
        self.procs = [self.proc]

    def _patch(self):
        def fake_popen(cmd, **kwargs):
            self.cmd = cmd
            self.popen_kwargs.append(kwargs)
            return self.procs.pop(0)
        return [
            mock.patch.object(capture_semihosting.subprocess, "Popen", fake_popen),
        ]

    def test_cmd_pin_and_success_path(self):
        """cmd 逐条钉: init → reset halt → semihosting enable → resume →
        sleep(采集窗 ms) → halt → shutdown; cwd=workspace; 成功返回原文"""
        with self._patch()[0]:
            stdout, stderr = capture_semihosting.run_semihosting_session(
                10, workspace="W")
        self.assertEqual(stdout, "LED ON\n")
        self.assertEqual(stderr, "TGL 3\n")
        self.assertEqual(self.cmd, [
            capture_semihosting.load_machine()["openocd_exe"],
            "-f", "interface/stlink.cfg",
            "-f", "target/stm32f1x.cfg",
            "-c", "transport select swd",
            "-c", "init",
            "-c", "reset halt",
            "-c", "arm semihosting enable",
            "-c", "resume",
            "-c", "sleep 10000",   # OpenOCD sleep 单位是 ms (10s → 10000)
            "-c", "halt",
            "-c", "shutdown",
        ])
        self.assertEqual(self.popen_kwargs[0]["cwd"], "W")
        # 超时窗 = 采集窗 + 30s (启动开销覆盖, 原契约)
        self.assertEqual(self.proc.communicate_calls, [40])

    def test_timeout_raises_carrier_without_kill(self):
        """超时 → SemihostingTimeout 携带 proc, 且本模块绝不 kill——
        收尸权在调用方 _finish_capture_timeout (二次 communicate 拿部分输出)"""
        dead = _FakeProc(timeout_exc=subprocess.TimeoutExpired(cmd="x", timeout=40))
        self.procs = [dead]
        with self._patch()[0]:
            with self.assertRaises(capture_semihosting.SemihostingTimeout) as cm:
                capture_semihosting.run_semihosting_session(10, workspace=None)
        self.assertIs(cm.exception.proc, dead)
        self.assertFalse(dead.killed, "模块不得抢先 kill——二次回收在调用方")
        self.assertEqual(dead.communicate_calls, [40],
                         "超时路径只有初次 communicate, 无二次回收")

    def test_other_exception_propagates(self):
        """非超时异常原样抛出——由调用方 capture_failed 分支处理 (原行为)"""
        dead = _FakeProc(timeout_exc=ValueError("boom"))
        self.procs = [dead]
        with self._patch()[0]:
            with self.assertRaises(ValueError):
                capture_semihosting.run_semihosting_session(10, workspace=None)


if __name__ == "__main__":
    unittest.main()
