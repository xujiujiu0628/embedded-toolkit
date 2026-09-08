r"""版本号单一事实源核对钉 (F-073).

背景: 2026-09-08 发现 README「项目结构」段把 VERSION 标成 0.3, 而 VERSION
文件已是 0.4 —— 与本仓"文档单一事实源"纪律 (F-034, CONTRIBUTING 文档同步节)
冲突: 状态类事实存在两个权威副本必然漂移。

钉法: README 中任何"VERSION ... 当前 X.Y"形态的标注, 必须等于
`wb_common.toolkit_version()` (它读 VERSION 文件, 是代码侧唯一事实源)。
若 README 今后改为完全不写死版本号, 本测试会因"找不到标注"而失败 ——
那也是合法解法 (指向命令而非复制值), 届时请同步改写本测试并记账。
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

from wb_common import toolkit_version  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# README 中版本标注的形态: 行内含 "VERSION" 且声明 "当前 X.Y"
_VERSION_CLAIM_RE = re.compile(r"当前\s*v?(?P<ver>\d+\.\d+)")


class VersionSingleSourceTests(unittest.TestCase):

    def test_toolkit_version_reads_version_file(self):
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
            self.assertEqual(toolkit_version(), f.read().strip())

    def test_readme_version_claims_match_version_file(self):
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        claims = []
        for lineno, line in enumerate(readme.splitlines(), 1):
            if "VERSION" not in line:
                continue
            m = _VERSION_CLAIM_RE.search(line)
            if m:
                claims.append((lineno, m.group("ver"), line.strip()))
        # 防空转: 找不到任何标注时必须显式失败, 不允许静默通过
        self.assertTrue(
            claims,
            "README 已无 'VERSION ... 当前 X.Y' 标注——若这是有意改为"
            "指向单一事实源, 请同步改写本测试并记 CHANGELOG")
        for lineno, ver, line in claims:
            with self.subTest(readme_line=lineno):
                self.assertEqual(
                    ver, toolkit_version(),
                    f"README:{lineno} 版本标注漂移: {line!r} "
                    f"(VERSION 文件 = {toolkit_version()})")


if __name__ == "__main__":
    unittest.main()
