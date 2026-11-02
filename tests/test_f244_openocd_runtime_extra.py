r"""F-244: openocd_runtime 的本地配置 / 命令构造 / 进程启停补测。

## 覆盖对象

`scripts/openocd_runtime.py` 此前 88% 覆盖（2026-11-02 实测）：
`load_local_config`/`save_local_config` 的显式脚本路径分支、`_machine_openocd_exe`
的异常回落、`swd_probe` 的 cfg 非法分支、`build_openocd_cmd` 的
board/interface/search/speed/transport/端口/extra 组合、`cleanup` 的
Win32/POSIX 两条终止路径、`start_openocd_server` 的 Popen 参数装配。

## 夹具

`subprocess` / `sys` / `signal` 用直接赋值替身（避免 test_stub_ratchet 的
B 式判据），用完还原；不启真进程。
"""
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_runtime  # noqa: E402
import wb_common  # noqa: E402


class LocalConfigTests(unittest.TestCase):
    def test_save_with_script_file(self):
        paths = []
        with mock.patch.object(openocd_runtime, "save_json_file",
                               side_effect=lambda p, d: paths.append(p)):
            openocd_runtime.save_local_config({"a": 1}, script_file=__file__)
        self.assertTrue(str(paths[0]).endswith(os.path.join("config", "openocd.json")))

    def test_save_without_script_file(self):
        paths = []
        with mock.patch.object(openocd_runtime, "save_json_file",
                               side_effect=lambda p, d: paths.append(p)):
            openocd_runtime.save_local_config({"a": 1})
        self.assertTrue(str(paths[0]).endswith("openocd.json"))

    def test_load_with_script_file(self):
        with mock.patch.object(openocd_runtime, "load_json_file",
                               return_value={"x": 1}) as spy:
            self.assertEqual(openocd_runtime.load_local_config(__file__), {"x": 1})
        self.assertTrue(spy.called)


class MachineExeTests(unittest.TestCase):
    def test_exception_returns_empty(self):
        with mock.patch.object(wb_common, "load_machine", side_effect=RuntimeError("boom")):
            self.assertEqual(openocd_runtime._machine_openocd_exe(), "")


class SwdProbeCfgTests(unittest.TestCase):
    def test_invalid_cfg_reported(self):
        with mock.patch.object(openocd_runtime, "resolve_openocd_cfg",
                               side_effect=openocd_runtime.OpenocdCfgError("bad cfg")):
            ok, tail = openocd_runtime.swd_probe("openocd", attempts=1)
        self.assertFalse(ok)
        self.assertIn("bad cfg", tail)


class BuildCmdTests(unittest.TestCase):
    def test_full_command(self):
        cmd = openocd_runtime.build_openocd_cmd(
            "openocd", board="b.cfg", search="/s", adapter_speed="1000",
            transport="swd", gdb_port=3333, telnet_port=4444,
            extra_commands=["init", "shutdown"])
        self.assertIn("/s", cmd)
        self.assertIn("b.cfg", cmd)
        self.assertIn("adapter speed 1000", cmd)
        self.assertIn("transport select swd", cmd)
        self.assertIn("gdb_port 3333", cmd)
        self.assertIn("telnet_port 4444", cmd)
        self.assertEqual(cmd[-4:], ["-c", "init", "-c", "shutdown"])

    def test_interface_target_when_no_board(self):
        cmd = openocd_runtime.build_openocd_cmd(
            "openocd", interface="i.cfg", target="t.cfg", gdb_port=None,
            telnet_port=None)
        self.assertIn("i.cfg", cmd)
        self.assertIn("t.cfg", cmd)
        self.assertFalse(any("gdb_port" in str(x) for x in cmd))


class CleanupTests(unittest.TestCase):
    def test_none_proc_is_noop(self):
        openocd_runtime.cleanup(None)

    def test_win32_terminates(self):
        calls = []

        class _Proc:
            def poll(self):
                return None

            def terminate(self):
                calls.append("terminate")

            def wait(self, timeout=None):
                calls.append("wait")

            def kill(self):
                calls.append("kill")

        old_sys = openocd_runtime.sys
        openocd_runtime.sys = SimpleNamespace(platform="win32")
        try:
            openocd_runtime.cleanup(_Proc())
        finally:
            openocd_runtime.sys = old_sys
        self.assertEqual(calls, ["terminate", "wait"])

    def test_timeout_then_kill(self):
        calls = []

        class _Proc:
            def poll(self):
                return None

            def terminate(self):
                calls.append("terminate")

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("cmd", 5)

            def kill(self):
                calls.append("kill")

        old_sys = openocd_runtime.sys
        openocd_runtime.sys = SimpleNamespace(platform="win32")
        try:
            openocd_runtime.cleanup(_Proc())
        finally:
            openocd_runtime.sys = old_sys
        self.assertEqual(calls, ["terminate", "kill"])

    def test_posix_sends_sigterm(self):
        calls = []

        class _Proc:
            def poll(self):
                return None

            def send_signal(self, sig):
                calls.append(("signal", sig))

            def wait(self, timeout=None):
                calls.append("wait")

        old_sys, old_signal = openocd_runtime.sys, openocd_runtime.signal
        openocd_runtime.sys = SimpleNamespace(platform="linux")
        openocd_runtime.signal = SimpleNamespace(SIGTERM=15)
        try:
            openocd_runtime.cleanup(_Proc())
        finally:
            openocd_runtime.sys, openocd_runtime.signal = old_sys, old_signal
        self.assertEqual(calls, [("signal", 15), "wait"])


class StartServerTests(unittest.TestCase):
    def test_popen_kwargs_assembled(self):
        captured = {}

        def _popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return SimpleNamespace()

        fake_sub = SimpleNamespace(
            Popen=_popen, PIPE=-1, CREATE_NEW_PROCESS_GROUP=0x200,
            TimeoutExpired=subprocess.TimeoutExpired)
        old_sub, old_sys = openocd_runtime.subprocess, openocd_runtime.sys
        openocd_runtime.subprocess = fake_sub
        openocd_runtime.sys = SimpleNamespace(platform="win32")
        try:
            with mock.patch.object(openocd_runtime, "hidden_subprocess_kwargs",
                                   return_value={}):
                openocd_runtime.start_openocd_server(["openocd"])
        finally:
            openocd_runtime.subprocess, openocd_runtime.sys = old_sub, old_sys
        self.assertEqual(captured["cmd"], ["openocd"])
        self.assertEqual(captured["kwargs"]["text"], True)
        self.assertTrue(captured["kwargs"]["creationflags"] & 0x200)


if __name__ == "__main__":
    unittest.main()
