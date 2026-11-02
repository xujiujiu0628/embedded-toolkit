r"""F-245: coverage_lint / capture_rtt / duration_profile 的边界分支补测。

## 覆盖对象

- `coverage_lint`：非目录 scripts/tests、语法错脚本、coverage 包缺失、
  analysis2 抛错/零语句文件、tests_dir 默认推断；
- `capture_rtt._rtt_cleanup`：正常终止与超时强杀；
- `duration_profile`：demo 文本路径与真实数据 warning 打印。
"""
import io
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import capture_rtt  # noqa: E402
import coverage_lint  # noqa: E402
import duration_profile  # noqa: E402


class CoverageLintEdgeTests(unittest.TestCase):
    def test_non_dir_scripts_yields_nothing(self):
        self.assertEqual(list(coverage_lint._iter_script_files(
            os.path.join(tempfile.gettempdir(), "no-such-dir"))), [])

    def test_non_dir_tests_yields_no_modules(self):
        self.assertEqual(coverage_lint._find_referenced_modules(
            os.path.join(tempfile.gettempdir(), "no-such-tests")), set())

    def test_syntax_error_script_has_empty_graph_node(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "broken.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("def broken(:\n")
            graph = coverage_lint._internal_import_graph(tmp)
        self.assertEqual(graph["broken"], set())

    def test_coverage_import_error_raises_environment_error(self):
        saved = sys.modules.get("coverage")
        sys.modules["coverage"] = None
        try:
            with self.assertRaises(EnvironmentError):
                coverage_lint._uncovered_from_coverage_data(
                    tempfile.gettempdir(), "x.coverage")
        finally:
            if saved is None:
                sys.modules.pop("coverage", None)
            else:
                sys.modules["coverage"] = saved

    def test_analysis_errors_and_zero_statement_files(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            for name, body in (("bad.py", "x = 1\n"),
                               ("empty.py", "# only comment\n"),
                               ("half.py", "y = 2\n")):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                    fh.write(body)
            data = os.path.join(tmp, "d.coverage")
            with open(data, "w", encoding="utf-8") as fh:
                fh.write("")

            class _Cov:
                def load(self):
                    pass

                def analysis2(self, full):
                    if full.endswith("bad.py"):
                        raise RuntimeError("not measured")
                    if full.endswith("empty.py"):
                        return (full, [], [], [], [])
                    return (full, [1, 2], [], [2], [])

            fake = types.ModuleType("coverage")
            fake.Coverage = lambda data_file=None: _Cov()
            saved = sys.modules.get("coverage")
            sys.modules["coverage"] = fake
            try:
                uncovered, pct = coverage_lint._uncovered_from_coverage_data(tmp, data)
            finally:
                if saved is None:
                    sys.modules.pop("coverage", None)
                else:
                    sys.modules["coverage"] = saved
        self.assertIn("bad.py", uncovered)
        self.assertNotIn("empty.py", uncovered)
        self.assertEqual(pct["half.py"], 50.0)

    def test_main_infers_tests_dir(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            scripts = os.path.join(tmp, "scripts")
            os.makedirs(scripts)
            with open(os.path.join(scripts, "a.py"), "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            os.makedirs(os.path.join(tmp, "tests"))
            out = io.StringIO()
            old = sys.argv
            sys.argv = ["coverage_lint.py", "--scripts-dir", scripts]
            try:
                with redirect_stdout(out):
                    rc = coverage_lint.main()
            finally:
                sys.argv = old
        self.assertEqual(rc, 0)


class RttCleanupTests(unittest.TestCase):
    def test_running_process_terminated(self):
        calls = []

        class _Proc:
            def poll(self):
                return None

            def terminate(self):
                calls.append("terminate")

            def wait(self, timeout=None):
                calls.append("wait")

            def kill(self):
                calls.append("kill")

        capture_rtt._rtt_cleanup(_Proc())
        self.assertEqual(calls, ["terminate", "wait"])

    def test_wait_timeout_kills(self):
        calls = []

        class _Proc:
            def poll(self):
                return None

            def terminate(self):
                calls.append("terminate")

            def wait(self, timeout=None):
                raise TimeoutError()

            def kill(self):
                calls.append("kill")

        capture_rtt._rtt_cleanup(_Proc())
        self.assertEqual(calls, ["terminate", "kill"])

    def test_none_is_noop(self):
        capture_rtt._rtt_cleanup(None)


class DurationProfileTailTests(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        old = sys.argv
        sys.argv = ["duration_profile.py", *argv]
        try:
            with redirect_stdout(out):
                rc = duration_profile.main()
        finally:
            sys.argv = old
        return rc, out.getvalue()

    def test_demo_text(self):
        rc, out = self._run(["--demo"])
        self.assertEqual(rc, 0)
        self.assertIn("source: demo", out)

    def test_real_legacy_warning_printed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ws:
            os.makedirs(os.path.join(ws, ".workbench", "state"))
            with open(os.path.join(ws, ".workbench", "state", "checkpoints.jsonl"),
                      "w", encoding="utf-8") as fh:
                fh.write('{"duration_sec": 1}\n\n')
            rc, out = self._run(["--project", ws])
        self.assertEqual(rc, 0)
        self.assertIn("[warn]", out)


if __name__ == "__main__":
    unittest.main()
