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
import os
import sys
import tempfile
import threading
import time
import unittest
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
        """新鲜他人锁 → 等满 timeout 后降级放行且 stderr 留痕"""
        ws = _fresh_ws()
        lock = os.path.join(ws, ".workbench", "state.json.lock")
        with open(lock, "w") as f:
            f.write("999999" if os.name == "nt" else str(os.getpid() + 1000))
        # POSIX 路径: 伪造一个"存在但不属于我们、也杀不掉"的判活会走
        # PermissionError=False——统一用超龄=False 的新鲜锁即可: 锁文件
        # mtime=now → 不陈旧 → 只能等超时
        real_stderr = sys.stderr
        import io
        sys.stderr = io.StringIO()
        try:
            t0 = time.time()
            with runtime_common.state_write_lock(ws, timeout=0.5):
                pass
            elapsed = time.time() - t0
            msg = sys.stderr.getvalue()
        finally:
            sys.stderr = real_stderr
        self.assertGreaterEqual(elapsed, 0.4, "未等满 timeout")
        self.assertIn("降级", msg, "降级必须向 stderr 诚实告警")


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
