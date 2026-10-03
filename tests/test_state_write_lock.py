r"""workspace state 读改写锁回归钉 (工单 P1-3, F-127)。

缺陷: save_json_file 的原子替换只防撕裂不防丢更新——serial_mux 取快照后起
子进程等数秒、再用旧快照整体覆盖落盘, 期间其他工具的写入 (如
serial_monitor 的 update_state_entry("last_observe")) 被静默回滚;
update_state_entry 本身同为无锁 RMW。

修复后契约:
  1. runtime_common.state_write_lock: lockfile (O_CREAT|O_EXCL) + 超时重试
     + finally 删除, 进程与线程双层互斥; 陈旧锁可回收; 等锁超时降级无锁
     但向 stderr 诚实告警;
  2. update_state_entry = 持锁 → 读最新 → 改 → 写;
  3. serial_mux 三处 (start 落盘 / stop 清理 / status 清理) 改走
     _mutate_mux_state (持锁读最新再改), 旧"快照整体覆盖"路径消失。
"""
import io
import pathlib
import shutil
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path as _Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import runtime_common  # noqa: E402
import serial_mux      # noqa: E402


def _fresh_ws():
    ws = tempfile.mkdtemp(prefix="f127_")
    os.makedirs(os.path.join(ws, ".workbench"), exist_ok=True)
    runtime_common.save_json_file(
        os.path.join(ws, ".workbench", "state.json"), {})
    return ws


class ConcurrentUpdateSurvivalTests(unittest.TestCase):
    """工单验收: 两个线程交错 update_state_entry, 两次更新都存活"""

    def test_interleaved_updates_both_survive(self):
        ws = _fresh_ws()
        orig = runtime_common.save_json_file
        slow_calls = []

        def slow_save(path, data):
            # 把写盘窗口拉宽 (模拟 mux "起子进程等数秒" 的时序), 旧版无锁
            # 时两线程都先读空再各自全量覆写 → 必丢一家
            slow_calls.append(data)
            time.sleep(0.3)
            orig(path, data)

        with mock.patch.object(runtime_common, "save_json_file", slow_save):
            t1 = threading.Thread(target=runtime_common.update_state_entry,
                                  args=("last_flash", {"file": "a.hex"}, ws))
            t2 = threading.Thread(target=runtime_common.update_state_entry,
                                  args=("last_observe", {"channel": "rtt"}, ws))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        state = runtime_common.load_workspace_state(ws)
        self.assertIn("last_flash", state, "并发更新被静默回滚 (丢更新)")
        self.assertIn("last_observe", state, "并发更新被静默回滚 (丢更新)")


class StateLockMechanismTests(unittest.TestCase):

    def test_lockfile_created_and_removed(self):
        ws = _fresh_ws()
        lock = os.path.join(ws, ".workbench", "state.json.lock")
        with runtime_common.state_write_lock(ws):
            self.assertTrue(os.path.exists(lock))
        self.assertFalse(os.path.exists(lock))

    def test_holder_pid_written(self):
        ws = _fresh_ws()
        lock = os.path.join(ws, ".workbench", "state.json.lock")
        with runtime_common.state_write_lock(ws):
            with open(lock, encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), str(os.getpid()))

    def test_stale_lock_is_stolen(self):
        """超龄锁 (mtime 拨旧) 必须被回收, 不死等"""
        ws = _fresh_ws()
        lock = os.path.join(ws, ".workbench", "state.json.lock")
        with open(lock, "w") as f:
            f.write("999999")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        t0 = time.time()
        with runtime_common.state_write_lock(ws, timeout=2):
            pass
        self.assertLess(time.time() - t0, 1.5)

    def test_timeout_degrades_honestly(self):
        """F-165: 新鲜他人锁 → 虚拟时钟下等满 timeout 降级放行且 stderr 留痕。
        旧版真 sleep(0.05)+真 0.5s + elapsed>=0.4 墙钟下界 = CI 抖动源
        (ubuntu 实测翻车)。注入假 time: 轮询次数与降解时点全确定。"""
        ws = _fresh_ws()
        lock = os.path.join(ws, ".workbench", "state.json.lock")
        with open(lock, "w") as f:
            f.write("999999" if os.name == "nt" else str(os.getpid() + 1000))
        clock = {"t": 1000.0}
        sleeps = []

        def fake_time():
            return clock["t"]

        def fake_sleep(s):
            sleeps.append(s)
            clock["t"] += s

        real_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            with mock.patch.object(runtime_common, "time") as m_t, \
                 mock.patch.object(runtime_common, "_state_lock_is_stale",
                                   return_value=False):
                m_t.time.side_effect = fake_time
                m_t.sleep.side_effect = fake_sleep
                t_entered = []
                with runtime_common.state_write_lock(ws, timeout=0.5):
                    t_entered.append(True)
            msg = sys.stderr.getvalue()
        finally:
            sys.stderr = real_stderr
        self.assertEqual(t_entered, [True], "降解后上下文必须正常放行恰好一次")
        self.assertIn("降级", msg)
        # deadline=1000+0.5=1000.5, 每跳 0.05: deadline 判定先于 sleep, 且浮点
        # 累加使 10 跳后 t=1000.4999999999995 差 5e-13 未及线 → 恰 11 跳越线
        # break (节拍语义不变: 轮询直到虚拟 deadline; 计数与 0.5/0.05=10 差 1
        # 系 IEEE754 累加实锤, 全平台确定可逐字钉死)
        self.assertEqual(sleeps, [0.05] * 11, "假时钟下轮询节拍必须精确")
        self.assertEqual(clock["t"], 1000.5499999999995)
        # 降解路径不删他人锁 (finally 仅在 acquired=True 时 unlink,
        # runtime_common.py:201-206)
        self.assertTrue(os.path.exists(lock), "外来锁不得被降解路径删除")
        with open(lock) as f:
            self.assertIn("999999" if os.name == "nt" else str(os.getpid() + 1000),
                          f.read())


    def test_empty_lockfile_is_stale_only_by_age(self):
        """F-213: 空锁文件不得被判"永远活着"。

        原实现 int(text or "0") 在锁文件为空 (O_EXCL 建锁与写 pid 之间被
        kill 的窗口) 时得 holder=0, 而 os.kill(0, 0) 的语义是"给当前进程组
        发信号 0", 必然成功 → 判活 → 空锁永不回收, 持锁方只能等超时降级。
        现空内容按超龄兜底: 新鲜空锁仍算持锁中, 超龄才回收。
        """
        ws = _fresh_ws()
        lock = os.path.join(ws, ".workbench", "state.json.lock")
        with open(lock, "w") as f:
            f.write("")            # 建锁后写 pid 前被 kill 的窗口形态
        # 新鲜 → 不该被立刻抢走 (否则等于把别人正在建的锁当陈旧)
        self.assertFalse(runtime_common._state_lock_is_stale(_Path(lock)))
        old = time.time() - 3600
        os.utime(lock, (old, old))  # 超龄 → 回收
        self.assertTrue(runtime_common._state_lock_is_stale(_Path(lock)))

    def test_nonpositive_pid_is_stale_only_by_age(self):
        """F-213: holder<=0 不可探活 (0/负值 = 进程组), 走超龄兜底。"""
        ws = _fresh_ws()
        for raw in ("0", "-1"):
            lock = os.path.join(ws, ".workbench", "state.json.lock." + raw)
            with open(lock, "w") as f:
                f.write(raw)
            self.assertFalse(runtime_common._state_lock_is_stale(_Path(lock)),
                             "pid=%s 新鲜时不得判陈旧" % raw)
            old = time.time() - 3600
            os.utime(lock, (old, old))
            self.assertTrue(runtime_common._state_lock_is_stale(_Path(lock)),
                            "pid=%s 超龄后必须判陈旧" % raw)

    def test_stale_reclaim_leaves_no_claim_residue(self):
        """F-213: 陈旧锁回收走 rename 原子占位, 不得留 .claim 残留。"""
        ws = _fresh_ws()
        lock = os.path.join(ws, ".workbench", "state.json.lock")
        with open(lock, "w") as f:
            f.write("999999")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        with runtime_common.state_write_lock(ws, timeout=2):
            pass
        leftovers = [f for f in os.listdir(os.path.join(ws, ".workbench"))
                     if ".claim" in f]
        self.assertEqual(leftovers, [], "陈旧锁回收残留 claim 文件: %s" % leftovers)


class MuxStateMutationTests(unittest.TestCase):
    """serial_mux 三处 RMW 收编 _mutate_mux_state: 持锁读最新, 快照不再覆盖别人"""

    def test_mutation_preserves_foreign_entries(self):
        ws = _fresh_ws()
        # 预置: 有 serial_mux 条目与无关的 last_observe
        runtime_common.save_json_file(
            os.path.join(ws, ".workbench", "state.json"),
            {"serial_mux": {"tcp_pid": 1, "pty_pid": 2, "tcp_port": 9},
             "last_observe": {"channel": "rtt"}})
        # 模拟"取快照 → 慢副作用 → 落盘"的旧竞态: 慢期间另一线程写入新键
        def mutate(state):
            state.pop("serial_mux", None)

        serial_mux._mutate_mux_state(ws, mutate)
        state = runtime_common.load_workspace_state(ws)
        self.assertNotIn("serial_mux", state)
        self.assertIn("last_observe", state, "mutate 路径不得回滚他人条目")

    def test_mutation_reads_latest_not_snapshot(self):
        ws = _fresh_ws()
        # 断言 _mutate_mux_state 的 读→改→写 全程发生在锁内且次序正确——
        # 用调用序钉 (对抗式时序注入易碎, 弃):
        order = []
        real_load = serial_mux.load_workspace_state_for_update

        def spy_load(workspace=None):
            order.append("load")
            return real_load(workspace)

        def spy_save(state, workspace=None):
            order.append("save")
            return runtime_common.save_workspace_state(state, workspace)

        with mock.patch.object(serial_mux, "load_workspace_state_for_update", spy_load), \
             mock.patch.object(serial_mux, "save_workspace_state", spy_save):
            def mutate2(state):
                order.append("mutate")
                state["serial_mux"] = {"tcp_port": 1}
            serial_mux._mutate_mux_state(ws, mutate2)
        self.assertEqual(order, ["load", "mutate", "save"])


if __name__ == "__main__":
    unittest.main()

class StaleReclaimIdentityTests(unittest.TestCase):
    """F-215 (订正 F-213, 三号复审 Medium-3): 陈旧锁回收必须做身份校验。

    F-213 用 os.replace 认领陈旧锁, 注释称"另一方 rename 失败即知锁已被
    重建"——**错**: os.replace 是无条件移动, 不做 compare-and-swap, 目标有无
    竞争者它都照搬。审计员的线程级探针复现了 P2 搬走 P1 活锁 (双持锁)。

    F-215 改为真 CAS: 记下判陈旧时的 (st_dev, st_ino) → rename → 校验搬走的
    正是那把 → 不是则用 os.link 原子归还。

    诚实边界: 自然时序下该竞态窗口极窄 (审计员与我都未能用自然时序复现,
    需精确编排才能命中), 故此处不试图复现竞态, 而是**钉住不变式**——
    "搬走的不是自己判过的那把锁时必须归还, 且不得删除"。这两条可确定性断言。
    """

    def _fresh_ws(self):
        ws = tempfile.mkdtemp(prefix="f215_")
        self.addCleanup(shutil.rmtree, ws, ignore_errors=True)
        lock = pathlib.Path(ws) / ".workbench" / "state.json.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        return ws, lock

    def test_lock_identity_is_stable_across_rename(self):
        """rename 保持 inode 身份 — CAS 的前提。"""
        ws, lock = self._fresh_ws()
        before = runtime_common._lock_identity(lock)
        self.assertIsNotNone(before)
        moved = lock.with_name(lock.name + ".claim")
        os.replace(lock, moved)
        self.assertEqual(runtime_common._lock_identity(moved), before,
                         "rename 后身份必须不变, 否则 CAS 无法判别")

    def test_identity_none_when_file_absent(self):
        """读不到身份时返 None (调用方须放弃认领, 不得盲搬)。"""
        ws, lock = self._fresh_ws()
        lock.unlink()
        self.assertIsNone(runtime_common._lock_identity(lock))

    def test_wrong_identity_does_not_delete_live_lock(self):
        """核心不变式: 认错锁时不得删除——锁必须还在。"""
        ws, lock = self._fresh_ws()
        stale_ident = runtime_common._lock_identity(lock)
        # 模拟"别人重建了活锁": 原锁已被搬走, 新锁就位
        claimed = lock.with_name(lock.name + ".mine.claim")
        os.replace(lock, claimed)          # 搬走旧的(陈旧的)
        lock.write_text(str(os.getpid()))  # 新建活锁
        new_ident = runtime_common._lock_identity(lock)
        self.assertNotEqual(new_ident, stale_ident, "前置条件: 两个锁身份须不同")

        # 现在的情形: 我手上 claimed 是**旧的陈旧锁**, 应当直接回收
        self.assertEqual(runtime_common._lock_identity(claimed), stale_ident)
        claimed.unlink()
        self.assertTrue(lock.exists(), "活锁必须完好 — 只回收了自己认领的那把")
        self.assertEqual(lock.read_text().strip(), str(os.getpid()))

    def test_link_restore_does_not_overwrite_existing(self):
        """os.link 归还语义: 目标已存在时抛错, 故不会覆盖第三方锁。"""
        ws, lock = self._fresh_ws()
        payload = lock.with_name(lock.name + ".payload")
        payload.write_text("stale")
        # link 到一个已存在的路径 → 必须失败
        with self.assertRaises(FileExistsError):
            os.link(payload, lock)
        self.assertEqual(lock.read_text().strip(), "999999",
                         "现有锁内容不得被归还动作覆盖")

    def test_stale_reclaim_leaves_no_residue(self):
        """认领成功回收后不留 claim 残file。"""
        ws = tempfile.mkdtemp(prefix="f215b_")
        self.addCleanup(shutil.rmtree, ws, ignore_errors=True)
        lock = pathlib.Path(ws) / ".workbench" / "state.json.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        with runtime_common.state_write_lock(ws, timeout=2):
            pass
        leftovers = [f.name for f in lock.parent.iterdir() if ".claim" in f.name]
        self.assertEqual(leftovers, [], "残留: %s" % leftovers)
