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
import queue
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


class _FirehoseProc:
    """启动爆发刷行的内存等价物 (真子进程管道预满态): Listening 首行 + N 行
    噪声, 灌完后流永久沉默——与真 OpenOCD gdb server 启动后状态同形 (先刷一
    波日志再挂起等连接)。pump 线程可在一个 GIL 时间片内灌入远超 maxsize(1000)
    行: F-166 前的"丢最旧"逐出策略恰好逐出队头就绪行, wait 永远等不到 ready
    (ubuntu-3.10 CI 确定性红的根因)。
    沉默尾巴是刻意的: 立即 EOF 的有限迭代器会走 pump 收尾"腾位保 EOF"路径,
    满队列时同样逐出一行行首——那是"进程已死"形态, 不是本钉要钉的存活服务
    稳态。drained 事件 = 全部爆发行已入队, 消费前等它即可零睡眠去抖。"""

    def __init__(self, n):
        lines = ["Listening on port 3333 for gdb connections\n"]
        lines += ["drain line %d %s\n" % (i, "x" * 80) for i in range(n)]
        self._it = iter(lines)
        self.stderr = self
        self.drained = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        line = next(self._it, None)
        if line is not None:
            return line
        self.drained.set()
        threading.Event().wait()  # 永久沉默: 不 StopIteration (不触发 EOF 腾位)

    def poll(self):
        return None  # 永不退出: 只钉队列逐出策略, 不涉进程生命周期


class StderrPumpDrainTests(unittest.TestCase):
    """排空钉: 真子进程持续向 stderr 灌大量行, ready 后主线程不再读也不死锁。
    F-166 增补: 启动爆发 >maxsize 行时就绪行存活钉 (逐出策略根因)。"""

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

    def test_startup_firehose_keeps_ready_line_alive(self):
        """F-166 根因钉: 启动爆发 (3x maxsize) 先于任何消费者时, 就绪行必须存活。
        旧"丢最旧"逐出策略在首批 >1000 行入队时把队头 Listening 行逐出,
        wait_server_ready 永远等不到就绪 (ubuntu-3.10 test_pump_drains 15s
        确定性超时红的根因) —— 回退为丢最旧本钉必红 (flip 红证见 CHANGELOG
        F-166)。钉两层: ①队列层 = 逐出策略本体 (确定性判别器, 无竞态:
        爆发全部入队后消费者才出现); ②端到端 = wait_server_ready 真调用。
        有界性同钉: 修复不得以牺牲 maxsize 上界为代价 ("长会话内存不增长")。"""
        # ① 队列层: pump 先于消费者灌满 3001 行 —— 保住的必须是流头部一段
        proc = _FirehoseProc(3000)
        q = openocd_runtime._start_stderr_pump(proc)
        self.assertTrue(proc.drained.wait(5), "pump 未排空启动爆发")
        head = q.get(timeout=1)
        self.assertEqual(head, "Listening on port 3333 for gdb connections\n")
        self.assertTrue(q.get(timeout=1).startswith("drain line 0 "),
                        "保留的应是爆发前段 (丢最新) 而非后段 (丢最旧=已回退)")
        kept = 2
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break
            kept += 1
        self.assertEqual(kept, q.maxsize,
                         "满队列应恰好保留 maxsize 行——有界内存契约不破")
        # ② 端到端: 同一形态直接喂真 wait 函数, ready 必须为 True
        ready, _ = openocd_runtime.wait_server_ready(
            _FirehoseProc(3000), 3333, timeout=3)
        self.assertTrue(ready,
                        "启动爆发后就绪行已死 —— 丢最旧回潮 (F-166)")


if __name__ == "__main__":
    unittest.main()
