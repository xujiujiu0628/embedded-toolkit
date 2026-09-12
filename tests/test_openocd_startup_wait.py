r"""openocd 启动等待收编回归钉 (工单 P0-7, F-123)。

缺陷 (三份逐字拷贝同病): wait_server_ready 用 proc.stderr.readline() 阻塞读
——进程存活但沉默时 readline 永不返回, 外层 while-timeout 检查不可达,
timeout 形同虚设; 且 server/itm 常驻会话 ready 后无人再读 stderr, OpenOCD
持续刷日志填满管道缓冲 (Windows ~64KB) 后自身阻塞 → 全链死锁。

修复后契约 (openocd_runtime 单实现 + 三入口 import):
  1. daemon 线程排空 stderr → 主循环非阻塞轮询, timeout 真实生效;
  2. 会话存活期 stderr 持续被排空, 不再有管道满死锁;
  3. 行为语义与旧版对齐: ready 前 Error 收集 / critical 词表否决 /
     进程退出即 False / itm 变体 grace 与全行返回。
"""
import itertools
import os
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_runtime  # noqa: E402


class _LiveProc:
    """poll() 恒 None (活着), stderr 是给定行的迭代器 (末尾阻塞=沉默)"""

    def __init__(self, lines):
        self.stderr = iter(lines)
        self._tail = threading.Event()  # never set: 模拟"活着但不再吐行"

    def poll(self):
        return None


class _SilentThenBlock:
    """stderr 永远无输出的假进程 (旧实现会在这里无限阻塞)"""

    def __init__(self):
        self.stderr = iter(itertools.repeat("", 0))  # 立即 StopIteration 不行——
        # 需要一个"永不产出"的迭代器:
        self.stderr = self

    def __iter__(self):
        return self

    def __next__(self):
        time.sleep(3600)  # readline 阻塞语义的等价物; 收编后不该有人调它
        raise StopIteration

    def poll(self):
        return None


class TimeoutActuallyWorksTests(unittest.TestCase):
    """工单验收: 假进程无输出时 wait 能在 timeout+余量内返回 False"""

    def test_server_variant_timeout_honored(self):
        proc = _SilentThenBlock()
        t0 = time.time()
        ready, errors = openocd_runtime.wait_server_ready(proc, 3333, timeout=1)
        self.assertFalse(ready)
        self.assertEqual(errors, [])
        self.assertLess(time.time() - t0, 5,
                        "timeout 形同虚设: 旧实现在 readline 上无限阻塞")

    def test_itm_variant_timeout_honored(self):
        proc = _SilentThenBlock()
        t0 = time.time()
        ready, lines = openocd_runtime.wait_itm_ready(proc, 3443, timeout=1)
        self.assertFalse(ready)
        self.assertLess(time.time() - t0, 5)


class ServerVariantSemanticsTests(unittest.TestCase):
    """gdb/telnet 口径: Listening 行=ready / Error 收集 / critical 否决 / 进程死=False"""

    def test_ready_after_noise(self):
        proc = _LiveProc([
            "Open On-Chip Debugger",
            "Error: some non-critical warning line",
            "Listening on port 3333 for gdb connections",
        ])
        ready, errors = openocd_runtime.wait_server_ready(proc, 3333, timeout=5)
        self.assertTrue(ready)
        self.assertEqual(errors, ["Error: some non-critical warning line"])

    def test_critical_error_before_ready_rejects(self):
        proc = _LiveProc([
            "Error: unable to open low-level " + "x" * 50,
            "Error: no device found",   # critical 词表命中
            "Listening on port 3333",
        ])
        ready, errors = openocd_runtime.wait_server_ready(proc, 3333, timeout=5)
        self.assertFalse(ready)
        self.assertTrue(any("no device found" in e for e in errors))

    def test_dead_process_returns_false_with_errors(self):
        proc = _LiveProc(["Error: init mode failed (unable to connect)"])
        proc.poll = lambda: 1  # 已退出
        ready, errors = openocd_runtime.wait_server_ready(proc, 3333, timeout=5)
        self.assertFalse(ready)
        self.assertTrue(errors)

    def test_lines_after_ready_do_not_flip_result(self):
        """ready 判定只看 ready 行之前的行 (旧版 break 语义)"""
        proc = _LiveProc([
            "Listening on port 3333",
            "Error: no device found",  # ready 之后才出现
        ])
        ready, errors = openocd_runtime.wait_server_ready(proc, 3333, timeout=5)
        self.assertTrue(ready)


class ItmVariantSemanticsTests(unittest.TestCase):
    """itm 口径: trace marker + grace 全行返回 / error: 即否决 / 返回 (ready, lines)"""

    def test_ready_grace_returns_all_lines(self):
        proc = _LiveProc([
            "timm names: itm",
            "tport 0 enabled",
            "listening on port 3443 for trace data",
        ])
        t0 = time.time()
        ready, lines = openocd_runtime.wait_itm_ready(proc, 3443, timeout=5)
        self.assertTrue(ready)
        self.assertGreaterEqual(time.time() - t0, 0.9)  # grace 攒够
        self.assertLess(time.time() - t0, 3)
        self.assertIn("timm names: itm", lines)  # 全行收集 (旧契约)

    def test_error_keyword_rejects_immediately(self):
        proc = _LiveProc(["Error: failed to start adapter's trace"])
        t0 = time.time()
        ready, lines = openocd_runtime.wait_itm_ready(proc, 3443, timeout=5)
        self.assertFalse(ready)
        self.assertLess(time.time() - t0, 1.5)  # 即时否决, 不等 timeout

    def test_silent_after_ready_exits_at_grace(self):
        """ready 后沉默: 靠时钟而不是 readline 返回推进 (旧版靠 readline 超时)"""
        proc = _SilentThenBlock()
        proc.stderr = iter(["listening on port 3443 for trace data"])
        ready, lines = openocd_runtime.wait_itm_ready(proc, 3443, timeout=5)
        self.assertTrue(ready)


class StderrPumpDrainTests(unittest.TestCase):
    """排空钉: 真子进程持续向 stderr 灌大量行, ready 后主线程不再读也不死锁"""

    CODE = (
        "import sys, time\n"
        "print('Listening on port 3333 for gdb connections', file=sys.stderr, flush=True)\n"
        "for i in range(40000):\n"
        "    print('drain line %d %s' % (i, 'x'*80), file=sys.stderr, flush=True)\n"
        "print('ALL_DONE', file=sys.stderr, flush=True)\n"
    )

    def test_pump_drains_without_blocking_writer(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", self.CODE],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace")
        try:
            ready, _ = openocd_runtime.wait_server_ready(proc, 3333, timeout=15)
            self.assertTrue(ready)
            # 主线程什么都不读, 等子进程自己吐完全部 3.2MB+ 并看到 ALL_DONE:
            # 旧实现 (无人排空) 时子进程必然卡在管道满上
            deadline = time.time() + 30
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
            self.assertIsNotNone(proc.poll(),
                                 "子进程被管道缓冲卡死 = stderr 未排空")
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if proc.stderr:
                proc.stderr.close()
            if proc.stdout:
                proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
