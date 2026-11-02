r"""F-239: coverage_lint 的文本报告与 main 进程内补测。

## 覆盖对象

`scripts/coverage_lint.py` 此前 71% 覆盖（2026-11-02 实测）：`_format_text_report`
与 `main()` 只被子进程用例触达，`coverage run` 不计入报告。本文件在进程内
调 main()，把 CLI 分支纳入覆盖率账本。

## 夹具

临时 `scripts/` + `tests/` 双目录：一个被 import 的模块（covered）+ 一个
无人 import 的模块（uncovered），静态可达闭包判定即红。
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

import coverage_lint  # noqa: E402


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["coverage_lint.py", *argv]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = coverage_lint.main()
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class FormatTextReportTests(unittest.TestCase):
    def test_no_gaps(self):
        text = coverage_lint._format_text_report([], "/s", "static-reachability")
        self.assertIn("0 个未覆盖文件", text)

    def test_lists_files_with_and_without_pct(self):
        text = coverage_lint._format_text_report(
            ["a.py", "b.py"], "/s", "coverage-data", {"a.py": 0.0})
        self.assertIn("- a.py  (executed 0.0% of statements)", text)
        self.assertIn("- b.py", text)
        self.assertNotIn("- b.py  (", text)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scripts = os.path.join(self.tmp.name, "scripts")
        self.tests = os.path.join(self.tmp.name, "tests")
        os.makedirs(self.scripts)
        os.makedirs(self.tests)
        self._write(os.path.join(self.scripts, "covered.py"), "def f():\n    return 1\n")
        self._write(os.path.join(self.scripts, "uncovered.py"), "def g():\n    return 2\n")
        self._write(os.path.join(self.tests, "test_covered.py"),
                    "import covered\n\n\ndef test_f():\n    assert covered.f() == 1\n")

    @staticmethod
    def _write(path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_text_report_lists_uncovered(self):
        rc, out, _ = _run(["--scripts-dir", self.scripts, "--tests-dir", self.tests])
        self.assertEqual(rc, 0)
        self.assertIn("uncovered.py", out)
        self.assertIn("static-reachability", out)

    def test_strict_exits_one(self):
        rc, _, _ = _run(["--scripts-dir", self.scripts, "--tests-dir", self.tests,
                         "--strict"])
        self.assertEqual(rc, 1)

    def test_json_contract(self):
        rc, out, _ = _run(["--scripts-dir", self.scripts, "--tests-dir", self.tests,
                           "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["tool"], "coverage_lint")
        self.assertEqual(payload["mode"], "static-reachability")
        self.assertIn("uncovered.py", payload["uncovered"])

    def test_missing_coverage_data_exits_two(self):
        """coverage 包缺失或数据文件不存在都走 exit 2（两条 EnvironmentError）。
        CI 的 unittest 腿不装 coverage，本机装了 → 断言两条文案都接受。"""
        rc, _, err = _run(["--scripts-dir", self.scripts, "--tests-dir", self.tests,
                           "--coverage-data", os.path.join(self.tmp.name, "no.coverage")])
        self.assertEqual(rc, 2)
        self.assertTrue("不存在" in err or "coverage 包" in err, err)


if __name__ == "__main__":
    unittest.main()
