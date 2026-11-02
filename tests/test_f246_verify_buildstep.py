r"""F-246: verify `_run_build_step` 的失败早退与 no-build 状态读取补测。

## 覆盖对象

`verify.py` 91% 的尾部：构建循环的 `build_has_errors` / `build_failed`
两条早退（含失败现场、checkpoint、输出），以及 `--no-build` 从
state.json 读取 hex/elf 产物的分支。
"""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


def _args(no_build=False):
    return SimpleNamespace(no_build=no_build, rebuild=False, json=True,
                           task_origin="manual", gate_run=False)


class BuildStepTests(unittest.TestCase):
    def _run(self, *, build, analyze=None, no_build=False, ws=None):
        result = {"steps": {}, "status": "ok"}
        old_ws = getattr(verify, "WORKSPACE", None)
        verify.WORKSPACE = ws
        try:
            with mock.patch.object(verify, "step_build", return_value=build), \
                    mock.patch.object(verify, "step_analyze",
                                      return_value=analyze or {"status": "ok",
                                                               "summary": {}}), \
                    mock.patch.object(verify, "_save_failure_context"), \
                    mock.patch.object(verify, "_output"), \
                    mock.patch.object(verify, "_record_checkpoint_early_exit"):
                try:
                    verify._run_build_step(_args(no_build), {}, "gcc", result, 0, 1)
                except SystemExit as exc:
                    return exc.code, result
        finally:
            verify.WORKSPACE = old_ws
        return None, result

    def test_analyze_error_early_exits_with_build_has_errors(self):
        rc, result = self._run(
            build={"status": "ok", "metrics": {"errors": 0}},
            analyze={"status": "error", "summary": {"errors": 3}})
        self.assertEqual(rc, 1)
        self.assertEqual(result["status"], "build_has_errors")
        self.assertIn("3 error", result["error"])

    def test_build_failure_early_exits(self):
        rc, result = self._run(build={"status": "error", "metrics": {}})
        self.assertEqual(rc, 1)
        self.assertEqual(result["status"], "build_failed")
        self.assertIn("Build failed", result["error"])

    def test_build_ok_returns_none(self):
        rc, result = self._run(build={"status": "ok", "metrics": {"errors": 0, "warnings": 0}})
        self.assertIsNone(rc)
        self.assertEqual(result["steps"]["build"]["status"], "ok")

    def test_no_build_reads_state_artifacts(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ws:
            os.makedirs(os.path.join(ws, ".workbench"))
            with open(os.path.join(ws, ".workbench", "state.json"), "w", encoding="utf-8") as fh:
                json.dump({"last_build": {"hex_file": "fw.hex", "elf_file": "fw.elf"}}, fh)
            rc, result = self._run(build={}, no_build=True, ws=ws)
        self.assertIsNone(rc)
        self.assertEqual(result["steps"]["build"]["status"], "skipped")

    def test_no_build_without_state(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ws:
            rc, result = self._run(build={}, no_build=True, ws=ws)
        self.assertIsNone(rc)
        self.assertEqual(result["steps"]["build"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
