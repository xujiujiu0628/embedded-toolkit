"""F-001 回归: feedback_db 首次落账死锁 (2026-08-30 代管期).

修复前: 工程根存在但 .workbench/feedback 目录尚不存在时, --log 以
"Error: 未找到工程根" exit 1 (误导性报错), 且 verify.py 侧 except 静默吞 —
新工程反馈事件永久丢失 (button-toggle 现役工程正是此现状, 建成以来零落账)。
修复: 无既有 feedback 目录时返回首选 .workbench/feedback 供 makedirs 创建;
仅真正未找到工程根才返回 None/exit 1。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts", "feedback_db.py")


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30, cwd=cwd)


class FeedbackDbFirstLogTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"))
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_first_log_creates_dir_and_succeeds(self):
        # 修复前此用例 returncode=1 ("未找到工程根" 误报) 且目录不创建
        r = _run(["--log", json.dumps({"pipeline": "build_fix",
                                       "outcome": "fixed"})], self.ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(
            os.path.join(self.ws, ".workbench", "feedback")))
        out = json.loads(r.stdout)
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["event_id"].startswith("bf_"))

    def test_stats_on_empty_project_returns_zero(self):
        # 读路径对无数据工程应返回空统计, 而非误报 exit 1
        r = _run(["--stats", "build_fix"], self.ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["total_events"], 0)

    def test_existing_embeddedskills_dir_still_preferred(self):
        # 迁移兼容: .embeddedskills/feedback 已存在时优先级不变 (不新建 .workbench)
        legacy = os.path.join(self.ws, ".embeddedskills", "feedback")
        os.makedirs(legacy)
        r = _run(["--log", json.dumps({"pipeline": "build_fix",
                                       "outcome": "fixed"})], self.ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(legacy, "feedback_db.json")))
        self.assertFalse(os.path.exists(
            os.path.join(self.ws, ".workbench", "feedback")))

    def test_no_project_root_still_errors(self):
        # 真无工程根时错误语义保持正确 (exit 1 + 明确提示)
        bare = tempfile.mkdtemp()
        try:
            r = _run(["--log", json.dumps({"pipeline": "build_fix"})], bare)
            self.assertEqual(r.returncode, 1)
            self.assertIn("未找到工程根", r.stderr)
        finally:
            shutil.rmtree(bare, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
