r"""锁面收口三笔 (F-232, 三号复审 N-7/N-8/N-9 同族一张票)。

| 条 | 缺陷 | 本票修法 |
|---|---|---|
| N-7 | `wb_common.file_lock` 只有 `blocking` 开关, 阻塞态无限等待 | 加 `timeout`, 超时抛 `TimeoutError` (不静默降级) |
| N-8 | `releases/<tag>.json` 两个写入方 (release.py finalize / release_audit.py --approve) 无共用锁 | 共用 `release_record_lock_path()` 派生的同一把哨兵 |
| N-9 | 陈旧锁 CAS 归还依赖 `os.link`, 不支持硬链的卷上失败且静默 | 抽 `_restore_claimed_lock`, 非 `FileExistsError` 的失败落 stderr 告警 + 退路归还 |

## 钉法说明

N-7/N-9 是原语行为, 用真跑钉 (真持锁 / 真 patch os.link); N-8 跨脚本,
用 AST 形态钉防"某一侧被改回裸写", 加一条真跑并发钉证明 approve 真的等待。

**为什么不静默降级**: `state_write_lock` 保护的是可再生的 state.json, 降级
代价只是一次丢更新; `file_lock` 保护的是 config.json / 发布记录这类**唯一
事实源**, 降级无锁执行等于把"两个进程互相覆盖"当成正常路径。故超时口径是
**响亮失败**(TimeoutError + 点名哨兵路径), 不是降级。
"""
import ast
import contextlib
import errno
import io
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import release  # noqa: E402
import release_audit  # noqa: E402
import runtime_common  # noqa: E402
from wb_common import file_lock, release_record_lock_path  # noqa: E402


def _file_lock_calls(node):
    """某函数内 file_lock(...) 调用的关键字实参表。"""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "file_lock":
            out.append({kw.arg for kw in n.keywords})
    return out


class FileLockTimeoutTests(unittest.TestCase):
    """N-7: 阻塞态必须有界, 且失败要响亮。"""

    def test_waiting_lock_times_out_and_raises_timeout_error(self):
        """持锁不放时, 第二个 file_lock(timeout=...) 不许无限等。"""
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "config.json")
            with file_lock(target):
                t0 = time.monotonic()
                with self.assertRaises(TimeoutError):
                    with file_lock(target, timeout=0.2):
                        pass
                elapsed = time.monotonic() - t0
                self.assertLess(elapsed, 5.0,
                                f"超时形同虚设: 等了 {elapsed:.2f}s")

    def test_timeout_error_names_the_sentinel(self):
        """报错必须点名哨兵路径 —— 否则用户不知道去查哪个锁。"""
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "config.json")
            with file_lock(target):
                try:
                    with file_lock(target, timeout=0.1):
                        pass
                except TimeoutError as e:
                    self.assertIn(target + ".lock", str(e))
                else:
                    self.fail("预期 TimeoutError, 实际未抛")

    def test_nonblocking_lock_still_raises_immediately(self):
        """回归钉: blocking=False 的既有语义 (试一下就走) 不许被 timeout 改掉。"""
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "config.json")
            with file_lock(target):
                t0 = time.monotonic()
                with self.assertRaises(OSError):
                    with file_lock(target, blocking=False, timeout=30):
                        pass
                self.assertLess(time.monotonic() - t0, 2.0)

    def test_custom_lock_path_is_used_instead_of_default_sentinel(self):
        """lock_path 覆盖: 哨兵落在指定处, 且默认处**不**新建哨兵。"""
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "releases", "v1.json")
            custom = os.path.join(td, ".workbench", "releases.v1.json.lock")
            with file_lock(target, lock_path=custom):
                self.assertTrue(os.path.exists(custom))
                self.assertFalse(os.path.exists(target + ".lock"))


class ReleaseRecordSharedLockTests(unittest.TestCase):
    """N-8: releases/<tag>.json 的两个写入方必须共用同一把锁。"""

    def test_record_lock_sentinel_sits_outside_releases_dir(self):
        """哨兵放在 .workbench/ 下: releases/ 里只有记录, 不混锁文件。"""
        p = release_record_lock_path(r"D:\ws", "v1.0.0")
        self.assertTrue(p.endswith("releases.v1.0.0.json.lock"))
        self.assertNotIn(os.sep + "releases" + os.sep, p)
        self.assertIn(".lock", os.path.basename(p))

    def test_both_writers_pass_lock_path_to_file_lock(self):
        """AST 形态钉: 两侧的 file_lock 调用都必须带 lock_path。

        只钉一侧 = 另一侧照旧裸写, 锁形同虚设 (F-222 教训: 锁要按目标文件
        被全部写入方共用)。
        """
        for mod, fn in ((release, "finalize"), (release_audit, "approve_record")):
            with open(mod.__file__, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            node = next((n for n in ast.walk(tree)
                         if isinstance(n, ast.FunctionDef) and n.name == fn), None)
            self.assertIsNotNone(node, f"{mod.__name__}.{fn} 不见了")
            calls = _file_lock_calls(node)
            self.assertTrue(calls, f"{mod.__name__}.{fn} 里没有 file_lock 调用")
            self.assertTrue(all("lock_path" in c for c in calls),
                            f"{mod.__name__}.{fn} 有 file_lock 调用没带 lock_path: {calls}")

    def test_approve_record_waits_for_the_shared_lock(self):
        """真跑: 别人持着记录锁时, approve_record 不许抢跑。"""
        ws = tempfile.mkdtemp()
        try:
            rec_dir = os.path.join(ws, ".workbench", "releases")
            os.makedirs(rec_dir)
            rec_p = os.path.join(rec_dir, "v9.json")
            with open(rec_p, "w", encoding="utf-8") as f:
                f.write('{"tag": "v9", "evidence": "hardware_validated"}')
            done = {}
            lock_p = release_record_lock_path(ws, "v9")
            with file_lock(rec_p, lock_path=lock_p):
                t = threading.Thread(
                    target=lambda: done.update(result=release_audit.approve_record(ws, "v9")),
                    daemon=True)
                t.start()
                t.join(0.5)
                self.assertTrue(t.is_alive(),
                                "approve_record 未等锁就动手了 (记录锁未被它获取)")
            t.join(10)
            self.assertIn("result", done, "释放锁后 approve_record 仍未完成")
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


class _OsWithoutLink:
    """模块引用替换桩 (F-184 钦定形态): 只让 os.link 抛指定异常, 其余透传。

    不用 mock.patch("os.link") —— 那是 A 式全局打桩, 会被
    test_stub_ratchet 判新增违规, 也确实会把整个进程的 os.link 打掉。"""

    def __init__(self, exc):
        self._exc = exc

    def __getattr__(self, name):
        if name == "link":
            def _link(*a, **k):
                raise self._exc
            return _link
        return getattr(os, name)


class CasRestoreTests(unittest.TestCase):
    """N-9: 硬链不可用时的归还失败必须可见。"""

    def test_hardlink_unsupported_falls_back_and_warns(self):
        with tempfile.TemporaryDirectory() as td:
            claimed = Path(td) / "state.json.lock.4242.claim"
            lock_path = Path(td) / "state.json.lock"
            claimed.write_text("4242")
            err = io.StringIO()
            with mock.patch.object(runtime_common, "os",
                                   _OsWithoutLink(OSError(errno.EPERM, "not permitted"))):
                with contextlib.redirect_stderr(err):
                    ok = runtime_common._restore_claimed_lock(claimed, lock_path)
            self.assertTrue(ok, "退路归还未生效: 活锁被晾在 .claim 里")
            self.assertTrue(lock_path.exists())
            self.assertFalse(claimed.exists())
            self.assertIn("os.link", err.getvalue(),
                          "退还失败静默了 —— 正是 N-9 要消掉的那一种")

    def test_restore_never_overwrites_a_live_lock(self):
        """目标已存在 = 第三方刚建了新锁, 归还必须让路且不算异常。"""
        with tempfile.TemporaryDirectory() as td:
            claimed = Path(td) / "state.json.lock.4242.claim"
            lock_path = Path(td) / "state.json.lock"
            claimed.write_text("4242")
            lock_path.write_text("9999")
            err = io.StringIO()
            with mock.patch.object(runtime_common, "os",
                                   _OsWithoutLink(FileExistsError(errno.EEXIST, "exists"))):
                with contextlib.redirect_stderr(err):
                    ok = runtime_common._restore_claimed_lock(claimed, lock_path)
            self.assertFalse(ok)
            self.assertEqual(lock_path.read_text(), "9999", "第三方活锁被覆盖")
            self.assertEqual(err.getvalue(), "", "让路是设计内行为, 不该告警")

    def test_state_write_lock_routes_restore_through_helper(self):
        """AST 形态钉: state_write_lock 里手写的 os.link 归还路径必须已收编。"""
        with open(runtime_common.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "state_write_lock")
        self.assertIn("_restore_claimed_lock", _called_names_in(node))


def _called_names_in(node):
    return {n.func.id for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


if __name__ == "__main__":
    unittest.main()
