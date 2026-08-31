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
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import feedback_db  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts", "feedback_db.py")


def _run(args, cwd):
    # 锁死子进程输出编码: 否则 stderr 随父终端 code page 漂移 (GBK 控制台下
    # 中文断言变乱码假失败——换回当日 Git Bash 实锤, F-001 测试自身补编码纪律)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30, cwd=cwd, env=env)


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


class CorruptDbRebuildTests(unittest.TestCase):
    """F-014: 校准库损坏不再裸崩全部落账 — 备份现场 + 空库重建"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"))
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)
        self.fb = os.path.join(self.ws, ".workbench", "feedback")
        os.makedirs(self.fb)
        self.old_cwd = os.getcwd()
        os.chdir(self.ws)  # 模块内 _feedback_dir 依赖 cwd
        self.addCleanup(os.chdir, self.old_cwd)
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)

    def _log(self):
        return feedback_db.log_event({"pipeline": "build_fix", "outcome": "fixed"})

    def test_corrupt_db_backed_up_and_rebuilt(self):
        # 修复前: 裸 JSONDecodeError, 落账全崩且 verify 侧无从区分
        with open(os.path.join(self.fb, "feedback_db.json"), "w",
                  encoding="utf-8") as f:
            f.write("{corrupt")
        eid = self._log()
        self.assertTrue(eid.startswith("bf_"))
        self.assertTrue(os.path.isfile(
            os.path.join(self.fb, "feedback_db.json.corrupt")))
        with open(os.path.join(self.fb, "feedback_db.json"),
                  encoding="utf-8") as f:
            db = json.load(f)
        self.assertEqual(db["total_events"], 1)

    def test_corrupt_calibration_backed_up_and_rebuilt(self):
        with open(os.path.join(self.fb, "calibration.json"), "w",
                  encoding="utf-8") as f:
            f.write("not json")
        # 带 error_code: update_calibration 才有校准 key, 会真正写回新库
        feedback_db.log_event({"pipeline": "build_fix", "error_code": "E42",
                               "outcome": "fixed"})
        self.assertTrue(os.path.isfile(
            os.path.join(self.fb, "calibration.json.corrupt")))
        with open(os.path.join(self.fb, "calibration.json"),
                  encoding="utf-8") as f:
            cal = json.load(f)
        # 重建空库上累计本次事件: attempts=1 且 fixed=1
        self.assertEqual(cal["build_fix"]["E42"]["attempts"], 1)
        self.assertEqual(cal["build_fix"]["E42"]["fixed"], 1)

    def test_empty_db_template_covers_all_pipelines(self):
        # F-014: 空库模板曾缺 verify/fresh_check 计数键 → 这两类事件只涨
        # total_events 不涨分类计数; 重建后的库应与 valid_pipelines 对齐
        db = feedback_db.load_feedback_db()  # 目录在但无 json → 空库模板
        for p in ("build_fix", "hardfault", "code_gen", "verify", "fresh_check"):
            self.assertIn(p, db["by_pipeline"])
        self._log()
        with open(os.path.join(self.fb, "feedback_db.json"),
                  encoding="utf-8") as f:
            db = json.load(f)
        self.assertEqual(db["by_pipeline"]["build_fix"], 1)

    def test_index_write_failure_keeps_event_file(self):
        # 两步写语义固化: 事件文件先落盘 — 索引写失败时事件孤悬可手工恢复
        with mock.patch.object(feedback_db, "save_feedback_db",
                               side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self._log()
        self.assertEqual(len(os.listdir(os.path.join(self.fb, "events"))), 1)


if __name__ == "__main__":
    unittest.main()
