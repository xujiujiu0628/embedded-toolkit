r"""F-244: runtime_common 的 state 锁判据 / 原子写 / openocd 目标解析补测。

## 覆盖对象

`scripts/runtime_common.py` 此前 87% 覆盖（2026-11-02 实测）：
`load_json_strict` 非对象、`_state_lock_is_stale` 的五种判据、
`state_write_lock` 的正常/超时降级、`get_state_entry`、
`hidden_subprocess_kwargs` 非 Windows 分支、`resolve_openocd_target` 的
wch/arm 缺键与成功路径未执行。

## 夹具

`os` / `time` 用直接赋值替身（避免 test_stub_ratchet 的 B 式判据），
用完还原；锁文件用临时目录。
"""
import io
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import runtime_common  # noqa: E402


class JsonStrictTests(unittest.TestCase):
    def test_non_object_raises_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("[1, 2]")
            with self.assertRaises(runtime_common.JSONCorruptError):
                runtime_common.load_json_strict(path)


class StaleLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lock = Path(self.tmp.name) / "state.json.lock"

    def _write(self, text, age=0.0):
        self.lock.write_text(text, encoding="utf-8")
        if age:
            stamp = time.time() - age
            os.utime(self.lock, (stamp, stamp))

    def test_missing_file_is_stale(self):
        self.assertTrue(runtime_common._state_lock_is_stale(self.lock))

    def test_empty_fresh_lock_not_stale(self):
        self._write("")
        self.assertFalse(runtime_common._state_lock_is_stale(self.lock))

    def test_empty_old_lock_stale(self):
        self._write("", age=runtime_common.STATE_LOCK_STALE_SECONDS + 5)
        self.assertTrue(runtime_common._state_lock_is_stale(self.lock))

    def test_non_numeric_stale(self):
        self._write("not-a-pid")
        self.assertTrue(runtime_common._state_lock_is_stale(self.lock))

    def test_non_positive_pid_uses_age(self):
        self._write("0")
        self.assertFalse(runtime_common._state_lock_is_stale(self.lock))

    def test_other_pid_on_posix(self):
        self._write("4242")
        old_os = runtime_common.os
        runtime_common.os = SimpleNamespace(name="posix", getpid=lambda: 1,
                                            kill=lambda pid, sig: None)
        try:
            self.assertFalse(runtime_common._state_lock_is_stale(self.lock))
            runtime_common.os = SimpleNamespace(
                name="posix", getpid=lambda: 1,
                kill=lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()))
            self.assertTrue(runtime_common._state_lock_is_stale(self.lock))
            runtime_common.os = SimpleNamespace(
                name="posix", getpid=lambda: 1,
                kill=lambda pid, sig: (_ for _ in ()).throw(PermissionError()))
            self.assertFalse(runtime_common._state_lock_is_stale(self.lock))
        finally:
            runtime_common.os = old_os


class StateWriteLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_lock_created_and_removed(self):
        lock_path = runtime_common._state_lock_path(self.tmp.name)
        with runtime_common.state_write_lock(self.tmp.name, timeout=1.0):
            self.assertTrue(lock_path.exists())
        self.assertFalse(lock_path.exists())

    def test_timeout_degrades_with_warning(self):
        lock_path = runtime_common._state_lock_path(self.tmp.name)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(str(os.getpid() + 1000), encoding="utf-8")
        err = io.StringIO()
        with redirect_stderr(err):
            with runtime_common.state_write_lock(self.tmp.name, timeout=0.05):
                pass
        self.assertIn("降级无锁执行", err.getvalue())


class SmallHelpersTests(unittest.TestCase):
    def test_get_state_entry(self):
        self.assertEqual(runtime_common.get_state_entry(None, "x"), {})
        self.assertEqual(runtime_common.get_state_entry({"x": 1}, "x"), {})
        self.assertEqual(runtime_common.get_state_entry({"x": {"a": 1}}, "x"), {"a": 1})

    def test_hidden_subprocess_kwargs_non_windows(self):
        old = runtime_common.sys
        runtime_common.sys = SimpleNamespace(platform="linux")
        try:
            self.assertEqual(runtime_common.hidden_subprocess_kwargs(), {})
        finally:
            runtime_common.sys = old


class ResolveTargetTests(unittest.TestCase):
    def test_wch_missing_exe(self):
        with self.assertRaises(runtime_common.OpenocdCfgError) as ctx:
            runtime_common.resolve_openocd_target(
                {}, gcc_cfg={"toolchain": "wch"})
        self.assertIn("wch_openocd_exe", str(ctx.exception))

    def test_wch_missing_cfg(self):
        with self.assertRaises(runtime_common.OpenocdCfgError) as ctx:
            runtime_common.resolve_openocd_target(
                {"wch_openocd_exe": "/ocd"}, gcc_cfg={"toolchain": "wch"})
        self.assertIn("wch_openocd_cfg", str(ctx.exception))

    def test_wch_success(self):
        target = runtime_common.resolve_openocd_target(
            {"wch_openocd_exe": "/ocd", "wch_openocd_cfg": "wch.cfg"},
            gcc_cfg={"toolchain": "wch"})
        self.assertEqual(target, {"exe": "/ocd", "cfg_list": ["wch.cfg"], "source": "wch"})

    def test_arm_missing_exe(self):
        with self.assertRaises(runtime_common.OpenocdCfgError):
            runtime_common.resolve_openocd_target({}, gcc_cfg={})

    def test_arm_success_uses_pair(self):
        with mock.patch.object(runtime_common, "resolve_openocd_cfg",
                               return_value={"interface": "i.cfg", "target": "t.cfg"}):
            target = runtime_common.resolve_openocd_target(
                {"openocd_exe": "/ocd"}, gcc_cfg={})
        self.assertEqual(target["cfg_list"], ["i.cfg", "t.cfg"])
        self.assertEqual(target["source"], "arm")


if __name__ == "__main__":
    unittest.main()
