r"""全仓语法卫生钉 (F-053).

scripts/ + tests/ 逐文件 compile, SyntaxWarning 与 DeprecationWarning 均升格
error——非法转义序列 (如 test_failure_hints.py 曾有的 `\.`) 在 Python 3.12+ 是
SyntaxWarning、3.10/3.11 是 DeprecationWarning, 两类都钉才跨版本有效。

背景: 非法转义不影响运行, 但会被 coverage_lint (F-049) 的 AST 全扫每轮吐到
stderr, 污染机器消费方的输出判读; 且它是"字符串里写了半截正则/路径"的信号,
值得在提交前拦住。
"""
import os
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SourceSyntaxHygieneTests(unittest.TestCase):
    def test_compile_all_sources_without_syntax_warnings(self):
        targets = []
        for sub in ("scripts", "tests"):
            for dirpath, dirs, files in os.walk(os.path.join(ROOT, sub)):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith(".py"):
                        targets.append(os.path.join(dirpath, f))
        self.assertGreater(len(targets), 0, "未收集到任何 .py, 扫描根配置有误")

        problems = []
        for path in sorted(targets):
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    compile(src, path, "exec")
                except SyntaxError as e:
                    problems.append(f"{path}: SyntaxError: {e}")
                    continue
            for w in caught:
                if isinstance(w.message, (SyntaxWarning, DeprecationWarning)):
                    problems.append(
                        f"{path}: {w.category.__name__}: L{w.lineno} {w.message}")

        self.assertEqual(
            [], problems,
            "存在语法卫生问题 (非法转义序列等)——修源码或改 raw 字符串, "
            "不要往扫描器里加豁免:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
