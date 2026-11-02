r"""F-242: mutation / handoff_guard / fsd_coverage 的 CLI 入口补测。

## 覆盖对象

三个模块此前分别 82% / 82% / 80% 覆盖（2026-11-02 实测），缺口都在
`main()` 的分支路由与退出码。既有用例走子进程（coverage 不追踪），本文件
在进程内调用，把 CLI 面纳入账本。

## 夹具

各模块的业务函数用模块引用替换；输入文件放临时目录。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import fsd_coverage  # noqa: E402
import handoff_guard  # noqa: E402
import mutation  # noqa: E402


def _call(module, argv, **patches):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = [module.__name__ + ".py", *argv]
    try:
        with mock.patch.multiple(module, **patches) if patches else _null():
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    rc = module.main()
                except SystemExit as exc:
                    rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *_x):
        return False


class MutationMainTests(unittest.TestCase):
    def _run(self, got):
        return _call(mutation, ["--project", ".", "--expect-red", "A",
                                "--edit", "m.c", "--find", "1", "--replace", "2"],
                     mutate_and_run=lambda *a, **k: got)

    def test_success_exit_zero(self):
        rc, _, _ = self._run({"ok": True, "summary": "done"})
        self.assertEqual(rc, 0)

    def test_failure_exit_one(self):
        rc, _, _ = self._run({"ok": False, "error": "boom"})
        self.assertEqual(rc, 1)


class HandoffGuardMainTests(unittest.TestCase):
    def test_clean_exit_zero(self):
        rc, out, err = _call(
            handoff_guard, ["--branch", "handoff/x"],
            guard=lambda *a, **k: {"verdict": "clean", "blocked": [], "warnings": []})
        self.assertEqual(rc, 0)
        self.assertIn('"verdict": "clean"', out)
        self.assertIn("blocked=0", err)

    def test_blocked_exit_one(self):
        rc, _, _ = _call(
            handoff_guard, ["--branch", "handoff/x"],
            guard=lambda *a, **k: {"verdict": "blocked", "blocked": [1], "warnings": []})
        self.assertEqual(rc, 1)

    def test_runtime_error_exit_two(self):
        def _boom(*_a, **_k):
            raise RuntimeError("not a repo")

        rc, _, err = _call(handoff_guard, ["--branch", "handoff/x"], guard=_boom)
        self.assertEqual(rc, 2)
        self.assertIn("not a repo", err)


class FsdCoverageMainTests(unittest.TestCase):
    def test_project_clean_exit_zero(self):
        with tempfile.TemporaryDirectory() as ws:
            rc, out, _ = _call(fsd_coverage, ["--project", ws, "--json"],
                               run_coverage=lambda _p: {"errors": [], "project": ws})
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["errors"], [])

    def test_project_errors_exit_one(self):
        with tempfile.TemporaryDirectory() as ws:
            rc, _, _ = _call(fsd_coverage, ["--project", ws, "--json"],
                             run_coverage=lambda _p: {"errors": ["E1"], "project": ws})
        self.assertEqual(rc, 1)

    def test_positional_files_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            fsd = os.path.join(tmp, "FSD.md")
            man = os.path.join(tmp, "expectations.json")
            with open(fsd, "w", encoding="utf-8") as fh:
                fh.write("# FSD\n")
            with open(man, "w", encoding="utf-8") as fh:
                json.dump({"expectations": []}, fh)
            rc, out, _ = _call(
                fsd_coverage, [fsd, man, "--json"],
                reconcile=lambda text, mobj: {"errors": [], "rows": []})
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["project"], fsd)

    def test_unreadable_input_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, _, err = _call(
                fsd_coverage, [os.path.join(tmp, "no.md"), os.path.join(tmp, "no.json")])
        self.assertEqual(rc, 2)
        self.assertIn("输入不可读", err)

    def test_no_project_and_not_in_tree_exit_two(self):
        rc, _, err = _call(
            fsd_coverage, [], find_project_root=lambda _cwd: None)
        self.assertEqual(rc, 2)
        self.assertIn("未指定 --project", err)


if __name__ == "__main__":
    unittest.main()
