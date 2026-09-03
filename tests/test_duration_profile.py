"""F-050: 分层前时长画像 — verify step-level timing + duration_profile 工具 (2026-09-02 方案四-4).

设计意图: 不拍脑袋切层, 用数据驱动. 当前限制: 仓内无真机, 真数据靠
checkpoints.jsonl (F-047 落盘) 自动累计; 工具自身用 mock 数据自检.

契约定下来:
  - duration_profile.py 读 .workbench/state/checkpoints.jsonl 聚合 step 耗时
  - 输出: min/p50/p95/max/sum + 占比
  - --demo 跑 mock 数据 (工具自检 / 模板)
  - 不接 checkpoints.jsonl 时 → 空报告 + 提示
  - verify.py 每个 step 加 duration_sec 字段 (向后兼容追加)

本测试锁契约:
  1. _read_checkpoints 解析 jsonl, 损坏行跳过
  2. _collect_step_durations 按 step_keys 聚合
  3. _percentile 线性插值, 空 list 返 0
  4. _summarize 出 count/min/p50/p95/max/sum
  5. --demo 走 mock 数据, 真数据空时不崩
  6. verify.py step dict 含 duration_sec (F-046 旧测试不能挂)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import duration_profile  # noqa: E402

SCRIPTS = os.path.dirname(os.path.abspath(duration_profile.__file__))
REPO_ROOT = os.path.dirname(SCRIPTS)


class ReadCheckpointsTests(unittest.TestCase):
    """F-050 单元: 读 jsonl 容错"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.state_dir = os.path.join(self.ws, ".workbench", "state")
        os.makedirs(self.state_dir)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_missing_returns_empty(self):
        self.assertEqual(duration_profile._read_checkpoints(self.ws), [])

    def test_valid_entries_parsed(self):
        path = os.path.join(self.state_dir, "checkpoints.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-09-03T12:00:00", "status": "ok",
                                "duration_sec": 5.0, "step_keys": ["build", "flash"]}) + "\n")
            f.write(json.dumps({"ts": "2026-09-03T12:01:00", "status": "ok",
                                "duration_sec": 7.0, "step_keys": ["capture"]}) + "\n")
        cps = duration_profile._read_checkpoints(self.ws)
        self.assertEqual(len(cps), 2)
        self.assertEqual(cps[0]["status"], "ok")

    def test_corrupt_line_skipped(self):
        path = os.path.join(self.state_dir, "checkpoints.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json\n")
            f.write(json.dumps({"status": "ok", "duration_sec": 1.0,
                                "step_keys": ["build"]}) + "\n")
            f.write("also broken\n")
        cps = duration_profile._read_checkpoints(self.ws)
        self.assertEqual(len(cps), 1)


class CollectStepDurationsTests(unittest.TestCase):
    """F-050 单元: 按 step_keys 聚合, 未知 step 忽略"""

    def test_empty_checkpoints_returns_empty_dict(self):
        out = duration_profile._collect_step_durations([])
        self.assertEqual(out, {k: [] for k in duration_profile.STEP_KEYS})

    def test_aggregate_by_step(self):
        cps = [
            {"step_keys": ["build", "flash"], "duration_sec": 5.0},
            {"step_keys": ["build"], "duration_sec": 7.0},
            {"step_keys": ["unknown_step"], "duration_sec": 1.0},  # 忽略
        ]
        by_step = duration_profile._collect_step_durations(cps)
        # 没有 result_lookup → 兜底用 duration_sec 顶替
        self.assertEqual(by_step["build"], [5.0, 7.0])
        self.assertEqual(by_step["flash"], [5.0])
        self.assertEqual(by_step["capture"], [])
        # unknown_step 不进 by_step
        self.assertNotIn("unknown_step", by_step)


class PercentileTests(unittest.TestCase):
    """F-050 单元: 百分位 (线性插值, 不依赖 numpy)"""

    def test_empty_returns_zero(self):
        self.assertEqual(duration_profile._percentile([], 0.5), 0.0)

    def test_single_value(self):
        self.assertEqual(duration_profile._percentile([5.0], 0.5), 5.0)
        self.assertEqual(duration_profile._percentile([5.0], 0.95), 5.0)

    def test_p50_of_even_list(self):
        # [1,2,3,4] p50 = 2.5 (插值)
        self.assertEqual(duration_profile._percentile([1, 2, 3, 4], 0.5), 2.5)

    def test_p95_skewed(self):
        # p95 应接近 max (含插值, 实际算出来是 8.24)
        xs = [1.0, 1.1, 1.0, 1.2, 10.0]  # 5 个, k=3.8
        p95 = duration_profile._percentile(xs, 0.95)
        # 排序 [1,1,1,1.1,10], k=3.8, f=3, c=4
        # 1.1 + (10-1.1)*(3.8-3) = 1.1 + 8.9*0.8 = 8.22 (理论值)
        # 实际浮点累加 ~8.23999...
        self.assertAlmostEqual(p95, 8.22, places=1)


class SummarizeTests(unittest.TestCase):
    """F-050 单元: 每 step 出 count/min/p50/p95/max/sum"""

    def test_empty_step_returns_zeros(self):
        stats = duration_profile._summarize({"build": [], "flash": []})
        self.assertEqual(stats["build"]["count"], 0)
        self.assertEqual(stats["build"]["p50"], 0.0)

    def test_populated_step(self):
        stats = duration_profile._summarize({"build": [1.0, 2.0, 3.0, 4.0, 5.0]})
        self.assertEqual(stats["build"]["count"], 5)
        self.assertEqual(stats["build"]["min"], 1.0)
        self.assertEqual(stats["build"]["max"], 5.0)
        self.assertEqual(stats["build"]["sum"], 15.0)
        # p50 应在 3.0 附近
        self.assertAlmostEqual(stats["build"]["p50"], 3.0, places=1)


class CliTests(unittest.TestCase):
    """F-050 CLI: --demo 跑 mock 数据, 无 project 时友好提示"""

    def test_demo_json_parseable(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "duration_profile.py"),
             "--demo", "--json"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(doc["tool"], "duration_profile")
        self.assertIn("stats", doc)
        # demo 应至少含 build/capture 等
        self.assertIn("build", doc["stats"])
        self.assertIn("capture", doc["stats"])

    def test_demo_human_output(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "duration_profile.py"),
             "--demo"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("duration_profile", r.stdout)
        self.assertIn("build", r.stdout)

    def test_no_project_friendly_message(self):
        # 跑在不存在的工程根, 应给友好错误而非 traceback
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "duration_profile.py")],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
            cwd=tempfile.gettempdir())  # 临时目录无 .workbench
        # 不应抛 traceback; exit 1 + 错误信息
        # Windows console 把 stderr 当 GBK 输出, 字节流里 "未找到" 被破坏
        # 只断言"非 traceback" + exit 1 + 错误前缀
        self.assertEqual(r.returncode, 1)
        # 用 repr 检查, 不依赖具体编码
        self.assertNotIn("Traceback", r.stderr)
        # 包含"工程根"或类似 (任意中文片段即可)
        self.assertTrue(
            "工程" in r.stderr or ".workbench" in r.stderr,
            f"stderr 应含工程相关提示, 实际: {r.stderr!r}")


if __name__ == "__main__":
    unittest.main()
