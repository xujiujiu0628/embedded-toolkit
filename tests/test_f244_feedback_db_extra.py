r"""F-244: feedback_db 的目录解析 / 损坏重建 / ID 生成补测。

## 覆盖对象

`scripts/feedback_db.py` 此前 85% 覆盖（2026-11-02 实测）：`_project_feedback_dir`
的三种目录形态、`_feedback_dir` 缺工程根早退、`_load_json_or_rebuild` 的
损坏隔离与备份失败两条告警、`make_event_id` 的未知流水线前缀与时间戳清洗、
`log_event` 的未知 pipeline/outcome 告警未执行。

## 夹具

临时工程 + 直接赋值替换 `os`（避免 test_stub_ratchet 的 B 式判据）。
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import feedback_db  # noqa: E402


class FeedbackDirTests(unittest.TestCase):
    def test_embeddedskills_preferred_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".embeddedskills", "feedback"))
            with mock.patch.object(feedback_db, "find_project_root", return_value=tmp):
                self.assertTrue(feedback_db._project_feedback_dir().endswith("feedback"))

    def test_default_workbench_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(feedback_db, "find_project_root", return_value=tmp):
                path = feedback_db._project_feedback_dir()
        self.assertTrue(path.replace("\\", "/").endswith(".workbench/feedback"))

    def test_no_project_root_exits_one(self):
        err = io.StringIO()
        with mock.patch.object(feedback_db, "find_project_root", return_value=None), \
                redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                feedback_db._feedback_dir()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("未找到工程根", err.getvalue())


class RebuildTests(unittest.TestCase):
    def test_corrupt_file_moved_aside(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "db.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{broken")
            err = io.StringIO()
            with redirect_stderr(err):
                data = feedback_db._load_json_or_rebuild(path, {"x": 1}, "db.json")
            self.assertEqual(data, {"x": 1})
            self.assertTrue(os.path.isfile(path + ".corrupt"))
            self.assertIn("从空库重建", err.getvalue())

    def test_backup_failure_warns_but_rebuilds(self):
        fake_os = SimpleNamespace(
            path=os.path,
            replace=lambda *a: (_ for _ in ()).throw(OSError("locked")))
        old = feedback_db.os
        feedback_db.os = fake_os
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "db.json")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("{broken")
                err = io.StringIO()
                with redirect_stderr(err):
                    data = feedback_db._load_json_or_rebuild(path, {"x": 1}, "db.json")
        finally:
            feedback_db.os = old
        self.assertEqual(data, {"x": 1})
        self.assertIn("备份失败", err.getvalue())


class EventIdTests(unittest.TestCase):
    def test_known_prefix(self):
        self.assertTrue(feedback_db.make_event_id(
            "hardfault", "2026-11-02T10:20:30").startswith("hf_"))

    def test_unknown_prefix_and_cleaning(self):
        eid = feedback_db.make_event_id("weird", "2026-11-02T10:20:30")
        self.assertEqual(eid, "ev_20261102_102030")


class LogEventWarningTests(unittest.TestCase):
    def test_unknown_pipeline_and_outcome_warn(self):
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, ".workbench"))
            with open(os.path.join(ws, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            old_cwd = os.getcwd()
            os.chdir(ws)
            err = io.StringIO()
            try:
                with redirect_stderr(err):
                    feedback_db.log_event({"pipeline": "weird",
                                           "outcome": "odd", "id": "x1"})
            finally:
                os.chdir(old_cwd)
        text = err.getvalue()
        self.assertIn("unknown pipeline", text)
        self.assertIn("unknown outcome", text)


if __name__ == "__main__":
    unittest.main()
