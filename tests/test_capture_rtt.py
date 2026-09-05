r"""capture_rtt 单元测试 (F-056) — RTT 时序的真单测（拆分前的盲区）.

拆分前 _step_capture_rtt 藏在 verify.py 里, socket/Popen 与编排逻辑纠缠,
只能靠 mock subprocess 隔山测 —— RTT 时序（本仓 F-003 级知识: rtt start 必须
在 resume+宽限之后, 防上一轮残留控制块造成假 PASS）从未被真实断言过。

注入方式: 不做构造注入, mock 本模块可见的共享模块对象——
  subprocess.Popen  → 假进程 (stderr 行可控, poll 可控)
  socket.create_connection → 按端口分发假 telnet (4444) / 假数据通道 (19021)
  time.sleep        → no-op (重试间隔/稳定期跳过, 时钟仍走真 time.time)
"""

import socket
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import capture_rtt  # noqa: E402


class _FakeTelnet:
    """假 telnet 会话: 记录发送的命令, 响应可编程"""

    def __init__(self, recorder, responses=None):
        self._recorder = recorder          # 跨连接共享的命令清单
        self._responses = list(responses or [])
        self._rx = [b"Open On-Chip Debugger > "]

    def recv(self, size):
        if self._rx:
            return self._rx.pop(0)
        if self._responses:
            return (self._responses.pop(0) + "\n> ").encode("utf-8")
        return b"> "

    def sendall(self, data):
        self._recorder.append(data.decode("utf-8").rstrip("\n"))

    def settimeout(self, t):
        pass

    def close(self):
        pass


class _FakeData:
    """假 RTT 数据通道: 先给一行正文, 之后一直超时"""

    def __init__(self):
        self._sent = False

    def recv(self, size):
        if not self._sent:
            self._sent = True
            return b"hello rtt\n"
        raise socket.timeout()

    def settimeout(self, t):
        pass

    def close(self):
        pass


class _FakeProc:
    """假 OpenOCD 进程: stderr 行可控, 存活状态可控"""

    def __init__(self, stderr_lines, alive=True):
        self.stderr = list(stderr_lines)
        self._alive = alive
        self.terminated = False

    def poll(self):
        return None if self._alive else 1

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


_LISTEN = ["Info : Listening on port 4444 for telnet connections"]


class SequencingTests(unittest.TestCase):
    """时序钉: telnet 命令顺序是本仓 F-003 级知识, 逐条断言"""

    def test_rtt_command_order_and_data_path(self):
        telnet_sent = []
        popen_kwargs = []
        telnet = _FakeTelnet(telnet_sent)
        data = _FakeData()

        def fake_popen(cmd, **kwargs):
            popen_kwargs.append(kwargs)
            return _FakeProc(_LISTEN, alive=True)

        def fake_conn(address, timeout=None):
            return telnet if address[1] == 4444 else data

        with mock.patch.object(capture_rtt.subprocess, "Popen", fake_popen), \
                mock.patch.object(capture_rtt.socket, "create_connection", fake_conn), \
                mock.patch.object(capture_rtt.time, "sleep", lambda s: None):
            out = capture_rtt.step_capture_rtt(1, {}, workspace="W")

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["_text"], "hello rtt\n")
        self.assertEqual(out["lines"], 1)
        # 时序钉: reset halt → resume → sleep 宽限 → rtt setup → rtt start
        # → polling_interval → server start（rtt start 在 resume 之后 = 防陈旧控制块假 PASS）
        self.assertEqual(telnet_sent[:7], [
            "reset halt", "resume", "sleep 300",
            'rtt setup 0x20000000 2048 "SEGGER RTT"',
            "rtt start", "rtt polling_interval 100",
            "rtt server start 19021 0",
        ])
        # 成功路径 finally 对存活会话的礼貌清理 (原有行为): halt + shutdown
        self.assertEqual(telnet_sent[7:], ["halt", "shutdown"])
        # workspace 参数化: OpenOCD 子进程 cwd 必须是工程根
        self.assertEqual(popen_kwargs[0]["cwd"], "W")


class FailurePathTests(unittest.TestCase):
    def test_control_block_not_found_is_not_retried(self):
        """控制块未找到 = 定性失败, 换会话也没用 → 恰好 1 次 spawn, 不空转"""
        telnet_sent = []
        popen_calls = []
        telnet = _FakeTelnet(telnet_sent,
                             responses=["Error: RTT control block not found"])
        proc = _FakeProc(_LISTEN, alive=True)

        with mock.patch.object(capture_rtt.subprocess, "Popen",
                               lambda cmd, **kw: (popen_calls.append(cmd), proc)[1]), \
                mock.patch.object(capture_rtt.socket, "create_connection",
                                  lambda address, timeout=None: telnet), \
                mock.patch.object(capture_rtt.time, "sleep", lambda s: None):
            out = capture_rtt.step_capture_rtt(1, {}, workspace=None)

        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"], "rtt_control_block_not_found")
        self.assertEqual(len(popen_calls), 1, "定性失败不得空转重试")
        # 存活进程失败后必须走 halt+shutdown 礼貌清理
        self.assertIn("halt", telnet_sent)
        self.assertIn("shutdown", telnet_sent)
        self.assertTrue(proc.terminated)

    def test_critical_error_after_listen_retries_three_times(self):
        """监听先于适配器失败打印的场景: 3 次重试纪律 + 每次都清理"""
        telnet_sent = []
        popen_calls = []
        telnet = _FakeTelnet(telnet_sent)
        proc = _FakeProc(_LISTEN + ["Error: open failed"], alive=True)

        with mock.patch.object(capture_rtt.subprocess, "Popen",
                               lambda cmd, **kw: (popen_calls.append(cmd), proc)[1]), \
                mock.patch.object(capture_rtt.socket, "create_connection",
                                  lambda address, timeout=None: telnet), \
                mock.patch.object(capture_rtt.time, "sleep", lambda s: None):
            out = capture_rtt.step_capture_rtt(1, {}, workspace=None)

        self.assertEqual(out["status"], "error")
        self.assertIn("open failed", out["error"])
        self.assertEqual(len(popen_calls), 3, "ST-Link 竞态 3 重试纪律")
        self.assertEqual(telnet_sent.count("halt"), 3)
        self.assertEqual(telnet_sent.count("shutdown"), 3)
        self.assertTrue(proc.terminated)

    def test_two_arg_call_stays_compatible(self):
        """wire 钉: 旧 2 参调用形态 (workspace 缺省 None) 必须继续可用"""
        popen_kwargs = []

        with mock.patch.object(capture_rtt.subprocess, "Popen",
                               lambda cmd, **kw: (popen_kwargs.append(kw),
                                                  _FakeProc([], alive=False))[1]), \
                mock.patch.object(capture_rtt.time, "sleep", lambda s: None):
            out = capture_rtt.step_capture_rtt(1, {})

        self.assertEqual(out["status"], "error")
        self.assertIsNone(popen_kwargs[0]["cwd"])


class ReadUntilPromptTests(unittest.TestCase):
    def _sock(self, chunks):
        class _S:
            def __init__(self, chunks):
                self._chunks = list(chunks)

            def recv(self, size):
                if not self._chunks:
                    return b""
                c = self._chunks.pop(0)
                if isinstance(c, Exception):
                    raise c
                return c

            def settimeout(self, t):
                pass

        return _S(chunks)

    def test_prompt_mid_buffer(self):
        s = self._sock([b"Info : x\nok\n> "])
        self.assertEqual(capture_rtt._rtt_read_until_prompt(s), "Info : x\nok")

    def test_peer_close_returns_buffer(self):
        s = self._sock([b"partial"])
        self.assertEqual(capture_rtt._rtt_read_until_prompt(s), "partial")

    def test_timeout_returns_buffer(self):
        s = self._sock([b"partial", socket.timeout()])
        self.assertEqual(capture_rtt._rtt_read_until_prompt(s), "partial")


if __name__ == "__main__":
    unittest.main()
