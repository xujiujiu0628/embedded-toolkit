r"""F-072 回归: coverage_lint 判定口径与真实覆盖率对齐。

历史缺陷 (2026-09-08 全仓 coverage 实测坐实): 旧口径只看"tests 是否直接
import 模块名", 与真实行覆盖率双向脱节——

  假阳 (本文件主钉): expectations.py 有 24 例测试, 但全部经 verify 再导出
    (tests 只 `import verify`), 旧口径报它"未覆盖", 真实覆盖 95%;
  假阴: 模块仅被 import 但逻辑从未执行, 旧口径算"已覆盖"。

钉法:
  1. 密封 fixture 复现 "tests → verify → expectations" 再导出链,
     断言 expectations.py 不再进未覆盖清单 (修复前该断言失败);
  2. 仓库级回归: 对真实 scripts/tests 跑静态模式, 断言历史上被误报的
     expectations.py 不在清单里;
  3. --coverage-data 真实覆盖模式: 生成真实 .coverage 数据, 断言
     "被 import 但从未执行"的文件被抓出 (封住假阴方向), 并校验 JSON
     契约新增的 mode / coverage_pct 字段。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import coverage_lint  # noqa: E402

SCRIPTS = os.path.dirname(os.path.abspath(coverage_lint.__file__))
REPO_ROOT = os.path.dirname(SCRIPTS)


def _coverage_available() -> bool:
    try:
        import coverage  # noqa: F401
        return True
    except ImportError:
        return False


class ReachabilityFixtureTests(unittest.TestCase):
    """密封 fixture: 再导出链必须计为已覆盖 (F-072 主场景)"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.scripts = os.path.join(self.ws, "scripts")
        self.tests = os.path.join(self.ws, "tests")
        os.makedirs(self.scripts)
        os.makedirs(self.tests)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _write(self, rel, text):
        with open(os.path.join(self.ws, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def _build_reexport_chain(self):
        """tests → verify → expectations (+ runtime_common), orphan 无引用"""
        self._write(os.path.join("scripts", "verify.py"),
                    "import expectations\nimport runtime_common\n")
        self._write(os.path.join("scripts", "expectations.py"), "X = 1\n")
        self._write(os.path.join("scripts", "runtime_common.py"), "Y = 2\n")
        self._write(os.path.join("scripts", "orphan.py"), "Z = 3\n")
        self._write(os.path.join("tests", "t1.py"), "import verify\n")

    def test_reexport_chain_counts_as_covered(self):
        """修复前: expectations.py / runtime_common.py 被误报未覆盖。"""
        self._build_reexport_chain()
        uncovered = coverage_lint._find_uncovered_scripts(
            self.scripts, self.tests)
        self.assertEqual(uncovered, ["orphan.py"])

    def test_direct_import_still_counts(self):
        self._write(os.path.join("scripts", "a.py"), "A = 1\n")
        self._write(os.path.join("scripts", "orphan.py"), "B = 1\n")
        self._write(os.path.join("tests", "t1.py"), "import a\n")
        self.assertEqual(
            coverage_lint._find_uncovered_scripts(self.scripts, self.tests),
            ["orphan.py"])

    def test_transitive_closure_two_hops(self):
        """tests → a → b → c: 三层再导出链全算已覆盖, 孤儿仍被报。"""
        self._write(os.path.join("scripts", "a.py"), "import b\n")
        self._write(os.path.join("scripts", "b.py"), "import c\n")
        self._write(os.path.join("scripts", "c.py"), "C = 1\n")
        self._write(os.path.join("scripts", "orphan.py"), "D = 1\n")
        self._write(os.path.join("tests", "t1.py"), "import a\n")
        self.assertEqual(
            coverage_lint._find_uncovered_scripts(self.scripts, self.tests),
            ["orphan.py"])

    def test_cycle_in_import_graph_does_not_hang(self):
        """a↔b 循环引用: 闭包必须终止, 两者都算可达。"""
        self._write(os.path.join("scripts", "a.py"), "import b\n")
        self._write(os.path.join("scripts", "b.py"), "import a\n")
        self._write(os.path.join("scripts", "orphan.py"), "C = 1\n")
        self._write(os.path.join("tests", "t1.py"), "import a\n")
        self.assertEqual(
            coverage_lint._find_uncovered_scripts(self.scripts, self.tests),
            ["orphan.py"])

    def test_unreachable_import_from_orphan_does_not_count(self):
        """可达性从 tests 的 seeds 出发: 孤儿 import 别人不把它带进来。"""
        self._write(os.path.join("scripts", "a.py"), "A = 1\n")
        self._write(os.path.join("scripts", "orphan.py"), "import a\n")
        self._write(os.path.join("tests", "t1.py"), "import a\n")
        self.assertEqual(
            coverage_lint._find_uncovered_scripts(self.scripts, self.tests),
            ["orphan.py"])


class RepoRegressionTests(unittest.TestCase):
    """仓库级回归: 历史误报条目必须消失 (对真实 scripts/tests 跑)"""

    def test_expectations_py_not_reported_uncovered(self):
        """修复前本断言失败: expectations.py 在旧口径未覆盖清单里,
        而其真实覆盖 95% (24 例测试经 verify 再导出)。"""
        uncovered = coverage_lint._find_uncovered_scripts(
            SCRIPTS, os.path.join(REPO_ROOT, "tests"))
        self.assertNotIn("expectations.py", uncovered)
        # 同链路的拆分件 (F-055~F-061) 也不应被误报
        for split_module in ("capture_rtt.py", "physical_gate.py",
                             "checkpoint_ledger.py", "failure_context.py",
                             "doctor.py", "capture_semihosting.py"):
            self.assertNotIn(split_module, uncovered)
        # 真零覆盖的文件仍必须被报 (防止口径从"假阳"摆到"全绿")
        self.assertIn("cube_to_keil.py", uncovered)
        # F-097: serial_mux 有了行为测试 (test_serial_mux_lifecycle) →
        # 不再零覆盖, 原钉移除; cube_to_keil 仍真零覆盖保留。
        # (P2-12 反向锁按"覆盖提升即移钉"纪律处理, 见 CHANGELOG F-097)
        self.assertNotIn("serial_mux.py", uncovered)


@unittest.skipUnless(_coverage_available(),
                     "coverage 包未安装 (CI 默认不装, 静态模式不受影响)")
class CoverageDataModeTests(unittest.TestCase):
    """--coverage-data 真实覆盖模式: 与真实行覆盖率同源判定"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.scripts = os.path.join(self.ws, "scripts")
        self.tests = os.path.join(self.ws, "tests")
        os.makedirs(self.scripts)
        os.makedirs(self.tests)
        # foo.py 会被 runner 真实执行; bar.py 只被 import 但语句从未执行
        with open(os.path.join(self.scripts, "foo.py"), "w",
                  encoding="utf-8") as f:
            f.write("def main():\n    return 42\n")
        with open(os.path.join(self.scripts, "bar.py"), "w",
                  encoding="utf-8") as f:
            f.write("import foo\n\ndef never_called():\n    return 1\n")
        with open(os.path.join(self.tests, "t1.py"), "w",
                  encoding="utf-8") as f:
            f.write("import bar\n")
        self.runner = os.path.join(self.ws, "runner.py")
        with open(self.runner, "w", encoding="utf-8") as f:
            f.write("import foo\nassert foo.main() == 42\n")
        self.data_file = os.path.join(self.ws, ".coverage")

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _generate_coverage_data(self):
        env = {**os.environ, "PYTHONPATH": self.scripts}
        subprocess.run(
            [sys.executable, "-m", "coverage", "run",
             "--data-file", self.data_file,
             "--source", self.scripts, self.runner],
            cwd=self.ws, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120, check=True,
            env=env)

    def test_imported_but_never_executed_is_reported(self):
        """假阴方向的封堵: bar 被 tests import, 但 0 条语句执行过 → 必须报。"""
        self._generate_coverage_data()
        uncovered, pct = coverage_lint._uncovered_from_coverage_data(
            self.scripts, self.data_file)
        self.assertIn("bar.py", uncovered)
        self.assertNotIn("foo.py", uncovered)
        self.assertEqual(pct["foo.py"], 100.0)
        self.assertEqual(pct["bar.py"], 0.0)

    def test_cli_json_contract_mode_and_pct(self):
        self._generate_coverage_data()
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "coverage_lint.py"),
             "--scripts-dir", self.scripts, "--tests-dir", self.tests,
             "--coverage-data", self.data_file, "--json"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(doc["mode"], "coverage-data")
        self.assertEqual(doc["coverage_data"], self.data_file)
        self.assertIn("bar.py", doc["uncovered"])
        self.assertIn("coverage_pct", doc)
        self.assertEqual(doc["coverage_pct"]["foo.py"], 100.0)

    def test_cli_static_mode_json_has_mode_field(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "coverage_lint.py"),
             "--scripts-dir", self.scripts, "--tests-dir", self.tests,
             "--json"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(doc["mode"], "static-reachability")
        # 静态口径的已知局限在此显式成钉: tests import bar, bar import foo
        # → 两者都"可达", 清单为空 —— 而 bar 实际 0 语句执行过。
        # 这正是 --coverage-data 模式存在的理由 (见上一用例)。
        self.assertEqual(doc["uncovered"], [])
        self.assertNotIn("coverage_pct", doc)

    def test_missing_data_file_exits_2(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "coverage_lint.py"),
             "--scripts-dir", self.scripts, "--tests-dir", self.tests,
             "--coverage-data", os.path.join(self.ws, "nope.coverage")],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("数据文件不存在", r.stderr)

    def test_strict_works_in_coverage_mode(self):
        self._generate_coverage_data()
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "coverage_lint.py"),
             "--scripts-dir", self.scripts, "--tests-dir", self.tests,
             "--coverage-data", self.data_file, "--strict"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("bar.py", r.stdout)


if __name__ == "__main__":
    unittest.main()
