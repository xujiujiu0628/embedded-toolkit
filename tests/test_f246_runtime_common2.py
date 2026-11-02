r"""F-246: runtime_common 的原子写失败 / 锁归还 / 陈旧锁回收补测。

## 覆盖对象

`runtime_common` 91% 的尾部：`atomic_write_json` 的 .tmp 清理、
`_state_lock_is_stale` 的自身 pid 分支、`_restore_claimed_lock` 的
FileExists/硬链失败/rename 成功/失败四态、`state_write_lock` 的陈旧锁
回收全链、`_serialize_state_value` 列表分支、损坏 state 隔离失败告警。
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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import runtime_common  # noqa: E402


class AtomicWriteFailureTests(unittest.TestCase):
    def test_tmp_removed_when_replace_fails(self):
        removed = []
        fake_os = SimpleNamespace(
            getpid=lambda: 4242,
            replace=lambda *a: (_ for _ in ()).throw(OSError("locked")),
            remove=lambda p: removed.append(p),
        )
        old = runtime_common.os
        runtime_common.os = fake_os
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                path = os.path.join(tmp, "x.json")
                with self.assertRaises(OSError):
                    runtime_common.save_json_file(path, {"a": 1})
        finally:
            runtime_common.os = old
        self.assertTrue(removed)

    def test_tmp_remove_failure_is_swallowed(self):
        fake_os = SimpleNamespace(
            getpid=lambda: 4242,
            replace=lambda *a: (_ for _ in ()).throw(OSError("locked")),
            remove=lambda p: (_ for _ in ()).throw(OSError("gone")),
        )
        old = runtime_common.os
        runtime_common.os = fake_os
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                with self.assertRaises(OSError):
                    runtime_common.save_json_file(
                        os.path.join(tmp, "x.json"), {"a": 1})
        finally:
            runtime_common.os = old


class StaleLockSelfPidTests(unittest.TestCase):
    def test_own_pid_uses_age(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            lock = Path(tmp) / "state.json.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")
            self.assertFalse(runtime_common._state_lock_is_stale(lock))
            stamp = time.time() - runtime_common.STATE_LOCK_STALE_SECONDS - 5
            os.utime(lock, (stamp, stamp))
            self.assertTrue(runtime_common._state_lock_is_stale(lock))


class RestoreClaimedLockTests(unittest.TestCase):
    def _run(self, link_impl, replace_impl=None, lock_exists=False):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            claimed = Path(tmp) / "state.json.lock.1.claim"
            lock = Path(tmp) / "state.json.lock"
            claimed.write_text("1", encoding="utf-8")
            if lock_exists:
                lock.write_text("2", encoding="utf-8")
            fake_os = SimpleNamespace(
                link=link_impl,
                replace=replace_impl or (lambda a, b: None),
            )
            old = runtime_common.os
            runtime_common.os = fake_os
            err = io.StringIO()
            try:
                with redirect_stderr(err):
                    result = runtime_common._restore_claimed_lock(claimed, lock)
            finally:
                runtime_common.os = old
        return result, err.getvalue()

    def test_link_file_exists_returns_false(self):
        def _link(_a, _b):
            raise FileExistsError()

        result, _ = self._run(_link)
        self.assertFalse(result)

    def test_link_unavailable_and_lock_taken(self):
        def _link(_a, _b):
            raise OSError("no hardlink")

        result, _ = self._run(_link, lock_exists=True)
        self.assertFalse(result)

    def test_link_unavailable_rename_fallback(self):
        def _link(_a, _b):
            raise OSError("no hardlink")

        result, _ = self._run(_link, replace_impl=lambda a, b: None)
        self.assertTrue(result)

    def test_rename_failure_returns_false(self):
        def _link(_a, _b):
            raise OSError("no hardlink")

        def _replace(_a, _b):
            raise OSError("locked")

        result, _ = self._run(_link, replace_impl=_replace)
        self.assertFalse(result)


class StaleReclaimTests(unittest.TestCase):
    def test_stale_lock_reclaimed_then_acquired(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ws:
            lock_path = runtime_common._state_lock_path(ws)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text("999999", encoding="utf-8")
            stamp = time.time() - runtime_common.STATE_LOCK_STALE_SECONDS - 5
            os.utime(lock_path, (stamp, stamp))
            with runtime_common.state_write_lock(ws, timeout=2.0):
                self.assertTrue(lock_path.exists())
            self.assertFalse(lock_path.exists())


class SerializeListTests(unittest.TestCase):
    def test_list_values_serialized(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ws:
            base = Path(ws)
            value = [os.path.join(ws, "a.txt"), "plain"]
            out = runtime_common._serialize_state_value(value, base)
        self.assertEqual(out[1], "plain")
        self.assertFalse(os.path.isabs(out[0]))


class CorruptIsolationFailureTests(unittest.TestCase):
    def test_isolation_failure_warns_and_rebuilds(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ws:
            os.makedirs(os.path.join(ws, ".workbench"))
            path = os.path.join(ws, ".workbench", "state.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{broken")
            fake_os = SimpleNamespace(
                replace=lambda *a: (_ for _ in ()).throw(OSError("locked")),
                remove=lambda p: None, path=os.path,
                makedirs=os.makedirs, getpid=os.getpid)
            old = runtime_common.os
            runtime_common.os = fake_os
            err = io.StringIO()
            try:
                with redirect_stderr(err):
                    data = runtime_common.load_workspace_state_for_update(ws)
            finally:
                runtime_common.os = old
        self.assertEqual(data, {})
        self.assertIn("隔离失败", err.getvalue())


if __name__ == "__main__":
    unittest.main()
