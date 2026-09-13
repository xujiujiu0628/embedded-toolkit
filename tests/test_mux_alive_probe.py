r"""is_mux_alive 探活回归钉 (工单 P0-1, F-117)。

缺陷: Windows 上 os.kill(pid, 0) 不是探活 —— CPython 对非 CTRL 类信号一律
TerminateProcess，"探活"会无条件杀掉被探测的 mux 进程；且 PID 不存在时
OpenProcess 失败抛 SystemError，(ProcessLookupError, PermissionError) 接不住。
调用链 open_serial_port → get_mux_info → is_mux_alive，每次开串口都触发。

修复后契约:
  1. Windows 分支走 TCP 连通性探测 (connect_ex 127.0.0.1:tcp_port)，绝不调 os.kill;
  2. POSIX 分支保留 os.kill(pid, 0) 语义;
  3. serial_mux 与 serial_runtime 共享同一实现 (单一定义, 再导出)。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_runtime  # noqa: E402


MUX_INFO = {"tcp_pid": 111, "pty_pid": 222, "tcp_port": 20001}


class WindowsProbeTests(unittest.TestCase):
    """Windows: TCP 探测，零 os.kill"""

    def _call(self, connect_ex_return: int):
        with mock.patch.object(serial_runtime.os, "name", "nt"), \
             mock.patch.object(serial_runtime, "socket") as sock_mod, \
             mock.patch.object(os, "kill") as kill_mock:
            instance = sock_mod.socket.return_value.__enter__.return_value
            instance.connect_ex.return_value = connect_ex_return
            alive = serial_runtime.is_mux_alive(dict(MUX_INFO))
        return alive, kill_mock, instance

    def test_windows_alive_uses_connect_ex_not_os_kill(self):
        alive, kill_mock, instance = self._call(0)
        self.assertTrue(alive)
        kill_mock.assert_not_called()
        instance.connect_ex.assert_called_once_with(("127.0.0.1", 20001))

    def test_windows_dead_port_returns_false(self):
        alive, kill_mock, _ = self._call(10035)  # WSAEINPROGRESS/拒绝连接类非零
        self.assertFalse(alive)
        kill_mock.assert_not_called()

    def test_windows_missing_tcp_port_returns_false(self):
        with mock.patch.object(serial_runtime.os, "name", "nt"), \
             mock.patch.object(os, "kill") as kill_mock:
            alive = serial_runtime.is_mux_alive({"tcp_pid": 1, "pty_pid": 2})
        self.assertFalse(alive)
        kill_mock.assert_not_called()


class PosixProbeTests(unittest.TestCase):
    """POSIX: 保留 os.kill(pid, 0) 探活"""

    def test_posix_uses_os_kill(self):
        with mock.patch.object(serial_runtime.os, "name", "posix"), \
             mock.patch.object(os, "kill") as kill_mock:
            alive = serial_runtime.is_mux_alive(dict(MUX_INFO))
        self.assertTrue(alive)
        self.assertEqual(kill_mock.call_count, 2)  # tcp_pid + pty_pid
        kill_mock.assert_any_call(111, 0)
        kill_mock.assert_any_call(222, 0)

    def test_posix_dead_pid_returns_false(self):
        with mock.patch.object(serial_runtime.os, "name", "posix"), \
             mock.patch.object(os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(serial_runtime.is_mux_alive(dict(MUX_INFO)))


class SingleDefinitionTests(unittest.TestCase):
    """收编钉: serial_mux 不得保留第二份实现 (P2-1 方向)"""

    def test_serial_mux_imports_shared_implementation(self):
        import serial_mux
        self.assertIs(serial_mux.is_mux_alive, serial_runtime.is_mux_alive)


if __name__ == "__main__":
    unittest.main()
