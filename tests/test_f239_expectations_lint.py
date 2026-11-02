r"""F-239: expectations_lint 的 CLI 出口补测。

## 覆盖对象

`scripts/expectations_lint.py` 此前 67% 覆盖（2026-11-02 实测）：E1~E15 判据
与 `lint_file` 分支已由 `test_expectations_lint.py` 覆盖，缺的是 `main()`
的路径解析（--path / --project / cwd 发现）与三种 verdict 输出。

## 夹具

临时工程 `.workbench/expectations.json`；cwd 发现用模块引用替换
`find_project_root`，不依赖真实目录树。
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

import expectations_lint  # noqa: E402

VALID = {"expectations": [
    {"id": "FR-A", "desc": "boot ok", "texts": ["LED ON"]},
]}


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["expectations_lint.py", *argv]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = expectations_lint.main()
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class LintFileMissingTests(unittest.TestCase):
    def test_missing_file_reports_e0(self):
        result = expectations_lint.lint_file(os.path.join(tempfile.gettempdir(), "no-such-exp.json"))
        self.assertEqual(result["errors"], ["E0: 文件不存在"])


class MainPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "expectations.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(VALID, fh, ensure_ascii=False)

    def test_valid_path_text_clean(self):
        rc, out, _ = _run([self.path])
        self.assertEqual(rc, 0)
        self.assertIn("CLEAN", out)
        self.assertIn("1 条期望全部合规", out)

    def test_valid_path_json_verdict(self):
        rc, out, _ = _run([self.path, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "clean")
        self.assertEqual(payload["item_count"], 1)

    def test_invalid_path_exit_one(self):
        bad = os.path.join(self.tmp.name, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        rc, out, _ = _run([bad])
        self.assertEqual(rc, 1)
        self.assertIn("[E]", out)

    def test_project_flag_resolves_workbench_path(self):
        proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(proj, ".workbench"))
        with open(os.path.join(proj, ".workbench", "expectations.json"), "w", encoding="utf-8") as fh:
            json.dump(VALID, fh, ensure_ascii=False)
        rc, out, _ = _run(["--project", proj, "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["verdict"], "clean")

    def test_cwd_discovery_when_no_path(self):
        proj = os.path.join(self.tmp.name, "cwdproj")
        os.makedirs(os.path.join(proj, ".workbench"))
        with open(os.path.join(proj, ".workbench", "expectations.json"), "w", encoding="utf-8") as fh:
            json.dump(VALID, fh, ensure_ascii=False)
        with mock.patch.object(expectations_lint, "find_project_root", return_value=proj):
            rc, out, _ = _run(["--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["verdict"], "clean")

    def test_no_path_and_no_project_exit_two(self):
        with mock.patch.object(expectations_lint, "find_project_root", return_value=None):
            rc, _, err = _run([])
        self.assertEqual(rc, 2)
        self.assertIn("未指定路径", err)


if __name__ == "__main__":
    unittest.main()
