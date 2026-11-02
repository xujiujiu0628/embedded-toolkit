r"""F-239: duration_profile 的真数据路径与文本报告补测。

## 覆盖对象

`scripts/duration_profile.py` 此前 60% 覆盖（2026-11-02 实测）：`_format_text`
的非空分支与 `main()` 的 `--project` 真数据路径（含 legacy 告警）未执行。
纯函数（读/聚合/百分位/汇总）与 demo CLI 已由 `test_duration_profile.py`
覆盖，本文件只补缺口。

## 夹具

临时工程 `.workbench/state/checkpoints.jsonl`，每行一条带 `step_durations`
的 checkpoint；不依赖真机。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import duration_profile  # noqa: E402


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["duration_profile.py", *argv]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = duration_profile.main()
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class FormatTextTests(unittest.TestCase):
    def test_populated_stats_render_rows_and_percentages(self):
        stats = {
            "build": {"count": 2, "min": 1.0, "p50": 1.5, "p95": 1.9,
                      "max": 2.0, "sum": 3.0},
            "capture": {"count": 2, "min": 5.0, "p50": 5.5, "p95": 5.9,
                        "max": 6.0, "sum": 11.0},
        }
        text = duration_profile._format_text(stats)
        self.assertIn("合计 14.0s", text)
        self.assertIn("build", text)
        self.assertIn("capture", text)
        self.assertIn("n=2", text)
        self.assertIn("%", text)

    def test_empty_stats_explains_demo(self):
        stats = {"build": {"count": 0}}
        self.assertIn("--demo", duration_profile._format_text(stats))


class RealPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "proj")
        state = os.path.join(self.ws, ".workbench", "state")
        os.makedirs(state)
        self.cp_path = os.path.join(state, "checkpoints.jsonl")
        rows = [
            {"step_durations": {"build": 2.0, "flash": 0.5}},
            {"step_durations": {"build": 4.0, "flash": 1.5}},
        ]
        with open(self.cp_path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    def test_json_output_aggregates_real_checkpoints(self):
        rc, out, _ = _run(["--project", self.ws, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertIn("real", payload["source"])
        self.assertEqual(payload["stats"]["build"]["count"], 2)
        self.assertEqual(payload["stats"]["build"]["max"], 4.0)
        self.assertEqual(payload["stats"]["flash"]["sum"], 2.0)

    def test_text_output_mentions_source(self):
        rc, out, _ = _run(["--project", self.ws])
        self.assertEqual(rc, 0)
        self.assertIn("duration_profile:", out)
        self.assertIn("[source: real", out)

    def test_legacy_entries_emit_warning(self):
        with open(self.cp_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"duration_sec": 3.0}) + "\n")
        rc, out, _ = _run(["--project", self.ws, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertTrue(payload["warnings"])
        self.assertIn("旧 F-047", payload["warnings"][0])

    def test_project_without_workbench_exits_one(self):
        bare = os.path.join(self.tmp.name, "bare")
        os.makedirs(bare)
        rc, _, err = _run(["--project", bare])
        self.assertEqual(rc, 1)
        self.assertIn("未找到工程根", err)


if __name__ == "__main__":
    unittest.main()
