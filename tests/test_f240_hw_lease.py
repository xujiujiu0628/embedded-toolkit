r"""F-240: hw_lease 的元数据读取、冲突文案与 CLI 派发补测。

## 覆盖对象

`scripts/hw_lease.py` 此前 75% 覆盖（2026-11-02 实测）：`_read_meta` 的
缺失/损坏/非对象回落、`_holder_message` 两种文案，以及 `main()` 的
status / acquire / release 三个出口未执行（既有用例主要测锁语义本体）。

## 夹具

CLI 用模块引用替换 `holder_info` / `acquire`，不碰真实设备锁目录。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hw_lease  # noqa: E402


def _run(argv):
    out = io.StringIO()
    err = io.StringIO()
    old = sys.argv
    sys.argv = ["hw_lease.py", *argv]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                rc = hw_lease.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old
    return rc, out.getvalue()


class LockPathTests(unittest.TestCase):
    def test_device_name_sanitized(self):
        lock_file, meta_file = hw_lease.lock_paths("st link/1")
        self.assertTrue(lock_file.endswith("st_link_1.lock"))
        self.assertTrue(meta_file.endswith("st_link_1.lock.meta.json"))


class ReadMetaTests(unittest.TestCase):
    def test_missing_returns_none(self):
        self.assertIsNone(hw_lease._read_meta(os.path.join(tempfile.gettempdir(), "no-meta.json")))

    def test_corrupt_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{broken")
            self.assertIsNone(hw_lease._read_meta(path))

    def test_non_object_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([1, 2], fh)
            self.assertIsNone(hw_lease._read_meta(path))

    def test_valid_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"purpose": "flash", "pid": 7}, fh)
            self.assertEqual(hw_lease._read_meta(path), {"purpose": "flash", "pid": 7})


class HolderMessageTests(unittest.TestCase):
    def test_with_meta_names_holder(self):
        msg = hw_lease._holder_message(
            {"purpose": "flash", "pid": 7, "acquired_at": "t"}, "stlink", 0)
        self.assertIn("purpose='flash'", msg)
        self.assertIn("pid=7", msg)
        self.assertNotIn("已等", msg)

    def test_without_meta_explains_crash_residue(self):
        msg = hw_lease._holder_message(None, "stlink", 1.5)
        self.assertIn("元数据缺失", msg)
        self.assertIn("已等 1.5s", msg)


class MainTests(unittest.TestCase):
    def test_status_without_holder(self):
        with mock.patch.object(hw_lease, "holder_info", return_value=None):
            rc, out = _run(["status"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertFalse(payload["held"])

    def test_status_with_holder(self):
        with mock.patch.object(hw_lease, "holder_info", return_value={"purpose": "flash"}):
            rc, out = _run(["status"])
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out)["held"])

    def test_acquire_ok_hides_fd(self):
        with mock.patch.object(hw_lease, "acquire",
                               return_value={"ok": True, "_fd": 3, "device": "stlink"}):
            rc, out = _run(["acquire", "--purpose", "flash"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertNotIn("_fd", payload)
        self.assertTrue(payload["ok"])

    def test_acquire_busy_exit_one(self):
        with mock.patch.object(hw_lease, "acquire",
                               return_value={"ok": False, "error": "resource_busy"}):
            rc, out = _run(["acquire", "--purpose", "flash"])
        self.assertEqual(rc, 1)
        self.assertIn("resource_busy", json.loads(out)["error"])

    def test_release_explains_cross_process_limit(self):
        rc, out = _run(["release"])
        self.assertEqual(rc, 1)
        self.assertIn("跨进程解锁", json.loads(out)["error"])

    def test_missing_subcommand_exits_two(self):
        rc, _ = _run([])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
