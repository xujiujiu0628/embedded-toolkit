r"""公开仓 tracked 文件裸机器路径静态扫描钉 (F-089)。

背景: F-067b 自订"路径全部中性化为 <d-claude-root> 占位, 不允许新 commit
再回写机器路径"——但 9-05 legacy/README 与 handoff_guard docstring 还是
带了 <d-claude-root> 形态 (F-069 二审 H-1 只查了 .github/, 漏了其余 tracked 文件)。
本钉把"零裸机器路径"变成机检: 维护者本机工作区根形态 (<d-claude-root> / <d-claude-root>,
大小写不敏感) 在 tracked 文件内零命中。

豁免: CHANGELOG.md —— 历史账目段属 append-only 保护区 (F-069 记账纪律:
"以本段为准/不改旧段"), 其中的路径是账目的一部分, 事后擦写会断证据链。
豁免是显式决策不是遗漏; 若未来账目段落入其他文件, 在此处追加豁免并记账。
"""
import os
import re
import subprocess
import unittest


class TrackedFilePathHygieneTests(unittest.TestCase):
    FORBIDDEN = re.compile("D:[/" + chr(92) + chr(92) + "/]claude", re.IGNORECASE)  # 字符集含反斜杠与正斜杠两种分隔符
    EXEMPT_FILES = {"CHANGELOG.md"}

    def _tracked_files(self):
        out = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return [f for f in out.stdout.splitlines()
                if f and f.endswith((".py", ".md"))]

    def test_no_bare_workspace_root_in_tracked_files(self):
        hits = []
        for f in self._tracked_files():
            base = os.path.basename(f)
            if base in self.EXEMPT_FILES:
                continue
            if not os.path.exists(f):
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if self.FORBIDDEN.search(line):
                        hits.append(f"{f}:{i}")
        self.assertEqual(
            hits, [],
            f"tracked 文件出现裸工作区根路径 (F-089 扫描钉):\n" + "\n".join(hits))

    def test_exemption_list_is_explicit_and_minimal(self):
        """豁免清单显式声明且最小——防静默扩大豁免面"""
        self.assertEqual(self.EXEMPT_FILES, {"CHANGELOG.md"})


if __name__ == "__main__":
    unittest.main()
