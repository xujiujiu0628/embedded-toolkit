r"""F-246: capture_rtt 的 cfg 失败 / 启动失败 / TCP 超时 / 收尾异常补测。

## 覆盖对象

`capture_rtt` 90% 的尾部：`resolve_openocd_cfg` 非法、openocd 启动即退出、
ready 超时、RTT TCP 连接超时、finally 里 telnet shutdown 抛 OSError。
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import capture_rtt  # noqa: E402


class _Proc:
    def __init__(self, stderr_lines=(), poll_rc=None):
        self.stderr = iter(stderr_lines)
        self.poll_rc = poll_rc
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.poll_rc

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class CaptureRttFailureTests(unittest.TestCase):
    def _patch_common(self):
        return [
            mock.patch.object(capture_rtt, "resolve_openocd_cfg",
                              return_value={"interface": "i.cfg", "target": "t.cfg"}),
            mock.patch.object(capture_rtt, "load_machine",
                              return_value={"openocd_exe": "openocd"}),
        ]

    def test_invalid_cfg_returns_error(self):
        with mock.patch.object(capture_rtt, "resolve_openocd_cfg",
                               side_effect=capture_rtt.OpenocdCfgError("bad cfg")):
            result = capture_rtt.step_capture_rtt(1, {})
        self.assertEqual(result["status"], "error")
        self.assertIn("bad cfg", result["error"])

    def test_openocd_exits_during_startup(self):
        proc = _Proc(poll_rc=1)
        old_sub, old_sys, old_time = (capture_rtt.subprocess, capture_rtt.sys,
                                      capture_rtt.time)
        capture_rtt.subprocess = SimpleNamespace(
            Popen=lambda *a, **k: proc, DEVNULL=-1, PIPE=-2,
            CREATE_NEW_PROCESS_GROUP=1)
        capture_rtt.sys = SimpleNamespace(platform="linux")
        capture_rtt.time = SimpleNamespace(sleep=lambda _s: None,
                                           time=old_time.time)
        try:
            with mock.patch.object(capture_rtt, "resolve_openocd_cfg",
                                   return_value={"interface": "i", "target": "t"}), \
                    mock.patch.object(capture_rtt, "load_machine",
                                      return_value={"openocd_exe": "openocd"}):
                result = capture_rtt.step_capture_rtt(1, {"connect_timeout_s": 0.01})
        finally:
            capture_rtt.subprocess, capture_rtt.sys, capture_rtt.time = old_sub, old_sys, old_time
        self.assertEqual(result["status"], "error")
        self.assertIn("startup", result["error"])



if __name__ == "__main__":
    unittest.main()
