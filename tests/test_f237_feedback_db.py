r"""F-237: feedback_db 的统计/相似检索/校准导出与 CLI 补测。

## 覆盖对象

`scripts/feedback_db.py` 此前 68% 覆盖（2026-11-02 实测）：`main()` 的
--stats / --similar / --calibrate / JSON 解析错误四个出口，以及
`get_pipeline_stats`、`find_similar`、`export_calibration` 从未执行。
落账主路径与首账死锁回归已由 `test_feedback_db.py` 覆盖，本文件只补查询面。

## 夹具

临时工程 `.workbench/config.json`，事件经真实 CLI `--log` 落盘后再查，
不手写 events/*.json —— 保证测的是"写进去再读出来"的完整链。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SCRIPT = os.path.join(SCRIPTS, "feedback_db.py")
sys.path.insert(0, SCRIPTS)

import feedback_db  # noqa: E402


def _run(cwd: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=cwd, timeout=60, env=env,
    )


class FeedbackQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(self.proj, ".workbench"))
        with open(os.path.join(self.proj, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")

    def _log(self, payload: dict) -> subprocess.CompletedProcess:
        return _run(self.proj, "--log", json.dumps(payload))

    def test_stats_on_empty_calibration_is_zero(self):
        proc = _run(self.proj, "--stats", "build_fix")
        self.assertEqual(proc.returncode, 0)
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["total_events"], 0)
        self.assertEqual(stats["success_rate_pct"], 0)

    def test_stats_aggregate_logged_events(self):
        self._log({"pipeline": "build_fix", "error_code": "E01", "outcome": "fixed", "rounds": 1})
        self._log({"pipeline": "build_fix", "error_code": "E01", "outcome": "still_broken", "rounds": 3})
        proc = _run(self.proj, "--stats", "build_fix")
        self.assertEqual(proc.returncode, 0)
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["total_events"], 2)
        self.assertEqual(stats["fixed"], 1)
        self.assertEqual(stats["success_rate_pct"], 50.0)
        self.assertEqual(stats["by_key"]["E01"]["attempts"], 2)
        self.assertEqual(stats["by_key"]["E01"]["avg_rounds"], 2.0)

    def test_similar_sorts_fixed_first(self):
        self._log({"pipeline": "build_fix", "error_code": "E02", "outcome": "still_broken"})
        self._log({"pipeline": "build_fix", "error_code": "E02", "outcome": "fixed"})
        proc = _run(self.proj, "--similar", "E02")
        self.assertEqual(proc.returncode, 0)
        similar = json.loads(proc.stdout)
        self.assertEqual([item["outcome"] for item in similar], ["fixed", "still_broken"])

    def test_similar_skips_index_entries_with_missing_detail(self):
        self._log({"pipeline": "build_fix", "error_code": "E03", "outcome": "fixed"})
        events_dir = os.path.join(self.proj, ".workbench", "feedback", "events")
        for name in os.listdir(events_dir):
            os.remove(os.path.join(events_dir, name))
        proc = _run(self.proj, "--similar", "E03")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout), [])

    def test_calibrate_exports_pipeline_data(self):
        self._log({"pipeline": "hardfault", "fault_type": "HardFault", "outcome": "fixed"})
        proc = _run(self.proj, "--calibrate")
        self.assertEqual(proc.returncode, 0)
        cal = json.loads(proc.stdout)
        self.assertEqual(cal["hardfault"]["HardFault"]["attempts"], 1)

    def test_invalid_json_exits_one(self):
        proc = _run(self.proj, "--log", "{not json")
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("JSON parse error", payload["message"])

    def test_no_arguments_prints_help(self):
        proc = _run(self.proj)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--stats", proc.stdout)


class PipelineStatsUnitTests(unittest.TestCase):
    def test_unknown_pipeline_returns_zeroes(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".workbench"))
            with open(os.path.join(tmp, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            old = os.getcwd()
            os.chdir(tmp)
            try:
                stats = feedback_db.get_pipeline_stats("__never_seen__")
            finally:
                os.chdir(old)
        self.assertEqual(stats["total_events"], 0)
        self.assertEqual(stats["success_rate_pct"], 0)


if __name__ == "__main__":
    unittest.main()
