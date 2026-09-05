"""F-049: 覆盖缺口 lint — 用 AST 扫描 scripts/ 下 .py 文件, 列出"未被任何 test_*.py
import 或函数级引用"的文件, 取代旧"行数红线"假命题 (2026-09-02 方案四-3).

判据说明 (与原"行数红线"对比):
  - 行数红线是假命题: 一个 200 行 const array 和一个 200 行状态机, 风险天差地别
  - 覆盖缺口是真问题: 工程师加了新模块, 忘了给测试加 hook, PC 测试编译过但
    这条路径根本没测到
  - 解决: scripts/ 下每个 .py 应当被某 test_*.py 通过 import / 函数引用

契约定下来:
  - 工具名: scripts/coverage_lint.py (与 expectations_lint 平级)
  - 用法: python scripts/coverage_lint.py [--scripts-dir DIR] [--tests-dir DIR]
                          [--strict] [--json]
  - 输出: 列出未被任何 test 引用的 scripts 文件
  - --strict: 存在未覆盖文件 → exit 1 (CI 门禁用)
  - 默认: 仅打印报告, exit 0 (诊断模式)
  - AST 判据: 扫 test_*.py 的 import / from-import, 收集所有引用的模块名
  - 文件名 fallback: 模块名 'foo' 也匹配 'foo.py' (主仓命名惯例)
  - legacy/ 目录豁免 (F-029 退役 keil 桥, 不强制覆盖)
  - 自身豁免: coverage_lint.py 自己的测试就是 coverage_lint_test.py
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


class FindReferencedModulesTests(unittest.TestCase):
    """F-049 单元: _find_referenced_modules() 扫 test_*.py 的 import 树"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_test_dir_returns_empty_set(self):
        self.assertEqual(coverage_lint._find_referenced_modules(self.tmp), set())

    def test_simple_import_collected(self):
        with open(os.path.join(self.tmp, "t1.py"), "w", encoding="utf-8") as f:
            f.write("import foo\nimport bar\n")
        mods = coverage_lint._find_referenced_modules(self.tmp)
        self.assertEqual(mods, {"foo", "bar"})

    def test_from_import_collected(self):
        with open(os.path.join(self.tmp, "t1.py"), "w", encoding="utf-8") as f:
            f.write("from baz import qux\n")
        mods = coverage_lint._find_referenced_modules(self.tmp)
        self.assertIn("baz", mods)
        # alias 名字 (qux) 不再被当作"被引用的脚本名"
        # 这是 F-049 自审 (2026-09-03) 修复: alias 是变量/类/函数, 不是文件名
        self.assertNotIn("qux", mods)

    def test_relative_from_import_no_alias_noise(self):
        # 相对 import: from .x import y → y 不应被算成"被引用的脚本"
        with open(os.path.join(self.tmp, "t1.py"), "w", encoding="utf-8") as f:
            f.write("from . import helper\n")
        mods = coverage_lint._find_referenced_modules(self.tmp)
        self.assertIn("helper", mods)
        # 'helper' 是 module 名, 不应同时塞 alias (此处 alias 同名)

    def test_relative_from_import_with_aliases(self):
        # 相对 import 带 alias: from .verify import main → 只算 'verify',
        # 不算 'main' (main 是函数, 不是脚本)
        with open(os.path.join(self.tmp, "t1.py"), "w", encoding="utf-8") as f:
            f.write("from .verify import main as entry\n")
        mods = coverage_lint._find_referenced_modules(self.tmp)
        self.assertIn("verify", mods)
        # alias 名 (main / entry) 都不应进 mods
        self.assertNotIn("main", mods)
        self.assertNotIn("entry", mods)

    def test_relative_import_collected(self):
        with open(os.path.join(self.tmp, "t1.py"), "w", encoding="utf-8") as f:
            f.write("from . import helper\nfrom .. import sibling\n")
        mods = coverage_lint._find_referenced_modules(self.tmp)
        # 相对 import 不带 . 前缀, 提取末段
        self.assertIn("helper", mods)
        self.assertIn("sibling", mods)

    def test_syntax_error_test_file_does_not_crash(self):
        with open(os.path.join(self.tmp, "t1.py"), "w", encoding="utf-8") as f:
            f.write("def broken(:\n")  # 语法错
        # 不应抛, 返回空 set (或至少不挂)
        mods = coverage_lint._find_referenced_modules(self.tmp)
        self.assertIsInstance(mods, set)

    def test_non_py_files_ignored(self):
        with open(os.path.join(self.tmp, "readme.md"), "w", encoding="utf-8") as f:
            f.write("import ghost\n")
        mods = coverage_lint._find_referenced_modules(self.tmp)
        self.assertEqual(mods, set())


class FindUncoveredScriptsTests(unittest.TestCase):
    """F-049 单元: _find_uncovered_scripts() 找"无引用"文件"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.scripts = os.path.join(self.ws, "scripts")
        self.tests = os.path.join(self.ws, "tests")
        os.makedirs(self.scripts)
        os.makedirs(self.tests)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _add_script(self, name):
        with open(os.path.join(self.scripts, name), "w", encoding="utf-8") as f:
            f.write("# placeholder\n")

    def _add_test(self, name, imports):
        with open(os.path.join(self.tests, name), "w", encoding="utf-8") as f:
            f.write(f"import {imports}\n")

    def test_all_covered_returns_empty(self):
        self._add_script("a.py")
        self._add_script("b.py")
        self._add_test("t1.py", "a, b")
        uncovered = coverage_lint._find_uncovered_scripts(
            self.scripts, self.tests)
        self.assertEqual(uncovered, [])

    def test_one_uncovered_detected(self):
        self._add_script("a.py")
        self._add_script("b.py")
        self._add_test("t1.py", "a")  # 只覆盖 a
        uncovered = coverage_lint._find_uncovered_scripts(
            self.scripts, self.tests)
        self.assertEqual(uncovered, ["b.py"])

    def test_legacy_subdir_excluded(self):
        # 2026-09-05 F-067b: Keil 退役区拆 archive 后 DIR_EXEMPT 清空,
        # 但 legacy/ 目录在 os.walk 中仍可下钻; 未来再有工具置入时按需
        # 重新加入 DIR_EXEMPT。本测试验证当前语义:
        # legacy/ 子树下的 .py 文件**会**被报告 (与其他未覆盖脚本同等),
        # 不再有"自动豁免"——这与 F-029 时期的"legacy/ 不强制覆盖"不同。
        os.makedirs(os.path.join(self.scripts, "legacy"))
        self._add_script("a.py")
        with open(os.path.join(self.scripts, "legacy", "old.py"), "w",
                  encoding="utf-8") as f:
            f.write("# old\n")
        self._add_test("t1.py", "a")
        uncovered = coverage_lint._find_uncovered_scripts(
            self.scripts, self.tests)
        # legacy/old.py 在结果里 (不再豁免)
        self.assertIn("legacy/old.py", uncovered)
        # a.py 不在 (有测试 a 引用)
        self.assertNotIn("a.py", uncovered)

    def test_coverage_lint_self_excluded(self):
        # coverage_lint.py 自身是工具, 它的测试就是 coverage_lint_test.py
        # 工具自检 — 不算"未覆盖"
        self._add_script("a.py")
        self._add_script("coverage_lint.py")
        self._add_test("t1.py", "a")
        uncovered = coverage_lint._find_uncovered_scripts(
            self.scripts, self.tests)
        # coverage_lint.py 不在结果 (工具豁免)
        self.assertNotIn("coverage_lint.py", uncovered)
        self.assertEqual(uncovered, [])


class CliTests(unittest.TestCase):
    """F-049 集成: --strict 旗标, --json 输出, 默认 exit 0"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.scripts = os.path.join(self.ws, "scripts")
        self.tests = os.path.join(self.ws, "tests")
        os.makedirs(self.scripts)
        os.makedirs(self.tests)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_json_output_parseable(self):
        with open(os.path.join(self.scripts, "orphan.py"), "w",
                  encoding="utf-8") as f:
            f.write("# placeholder\n")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "coverage_lint.py"),
             "--scripts-dir", self.scripts, "--tests-dir", self.tests,
             "--json"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertIn("uncovered", doc)
        self.assertIn("orphan.py", doc["uncovered"])

    def test_strict_exits_nonzero_on_uncovered(self):
        with open(os.path.join(self.scripts, "orphan.py"), "w",
                  encoding="utf-8") as f:
            f.write("# placeholder\n")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "coverage_lint.py"),
             "--scripts-dir", self.scripts, "--tests-dir", self.tests,
             "--strict"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("orphan.py", r.stdout)

    def test_default_exits_zero_with_uncovered(self):
        # 默认模式 (无 --strict): 仅报告, 不阻断
        with open(os.path.join(self.scripts, "orphan.py"), "w",
                  encoding="utf-8") as f:
            f.write("# placeholder\n")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "coverage_lint.py"),
             "--scripts-dir", self.scripts, "--tests-dir", self.tests],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("orphan.py", r.stdout)


if __name__ == "__main__":
    unittest.main()
