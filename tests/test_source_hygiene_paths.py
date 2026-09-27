r"""公开仓 tracked 文件裸机器路径/身份碎片静态扫描钉 (F-089, F-202 扩面)。

背景: F-067b 自订"路径全部中性化为 <d-claude-root> 占位, 不允许新 commit
再回写机器路径"——但 9-05 legacy/README 与 handoff_guard docstring 还是
带了裸工作区根形态 (F-069 二审 H-1 只查了 .github/, 漏了其余 tracked 文件)。
本钉把"零裸机器路径"变成机检。

F-202 扩面 (公开仓 v0.7 复审 H-1): 原单模式只钉 <旧工作区根> 一种形态,
且只扫 .py/.md——复审实测两类漏网: ① 另一私有工作区根的路径形态入账
(CHANGELOG 豁免面 + 叙述层); ② 机器路径借 .json 夹具/数据档入仓
(fixture _meta.cli、arch-facts source_root)。据此:

  模式三族 (全部大小写不敏感):
    1. 旧工作区根两种分隔符形态 (F-089 原钉, 反斜杠/正斜杠);
    2. 私有工作区名的路径组件形态 (前后均为分隔符才算——裸提名字不算,
       账目里"某项目名"叙述属事实记录, 只钉机器路径);
    3. 用户主目录下裸数字用户名的路径形态 (C\\Users\\<uid> 借夹具入仓
       的守卫面; 叙述层裸数字无从机检, 靠 F-202 清洗 + 复审)。
  扫描面: .py / .md / .json (F-202 加 .json)。
  豁免: CHANGELOG.md 对**模式 1** 豁免——历史账目段属 append-only 保护区
  (F-069 记账纪律: "以本段为准/不改旧段"), 其中的工具链路径是账目的一
  部分, 事后擦写会断证据链; 豁免是显式决策不是遗漏。**身份碎片 (模式
  2/3) 不享豁免**: 账目完整性不构成公开维护者私有工作区布局/本机账号
  的理由, test_changelog_no_identity_fragments 单独机检 (F-202)。

注意: 本 docstring 与源码刻意不出现模式 2/3 的字面量 (chr 码构造),
避免自扫描命中; 模式 1 的旧根名字面量沿 F-089 原式 (拼装位置不构成匹配)。

豁免清单变更纪律: 若未来账目段落入其他文件, 在此处追加豁免并记账。
"""
import os
import re
import subprocess
import unittest


def _s(*codes):
    """chr 码拼字符串——身份字面量不进源码 (自扫描不命中)。"""
    return "".join(chr(c) for c in codes)


_BS = chr(92)                                   # 反斜杠字面量
_SEP = "[/" + _BS + _BS + "/]"                  # 两种分隔符字符集
_FORBIDDEN_CLAUDE_LIKE = re.compile(
    "D:" + _SEP + "claude", re.IGNORECASE)      # F-089 原钉
_FORBIDDEN_PRIVATE_WS = re.compile(
    _SEP + _s(119, 111, 114, 100, 98, 117, 100, 100, 121) + _SEP,
    re.IGNORECASE)                              # 私有工作区名路径形态
_FORBIDDEN_USER_HOME = re.compile(
    _SEP + "Users" + _SEP + _s(51, 52, 51, 53, 52) + r"\b",
    re.IGNORECASE)                              # 用户主目录用户名路径形态

_IDENTITY_PATTERNS = (_FORBIDDEN_PRIVATE_WS, _FORBIDDEN_USER_HOME)


class TrackedFilePathHygieneTests(unittest.TestCase):
    FORBIDDEN = [
        _FORBIDDEN_CLAUDE_LIKE,
        _FORBIDDEN_PRIVATE_WS,
        _FORBIDDEN_USER_HOME,
    ]
    EXEMPT_FILES = {"CHANGELOG.md"}
    SCAN_EXTS = (".py", ".md", ".json")         # F-202: +.json (fixture/_meta 面)

    def _tracked_files(self):
        out = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return [f for f in out.stdout.splitlines()
                if f and f.endswith(self.SCAN_EXTS)]

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
                    for pat in self.FORBIDDEN:
                        if pat.search(line):
                            hits.append(f"{f}:{i} ({pat.pattern})")
                            break
        self.assertEqual(
            hits, [],
            "tracked 文件出现裸机器路径/身份碎片 (F-089+F-202 扫描钉):\n"
            + "\n".join(hits))

    def test_exemption_list_is_explicit_and_minimal(self):
        """豁免清单显式声明且最小——防静默扩大豁免面"""
        self.assertEqual(self.EXEMPT_FILES, {"CHANGELOG.md"})


class ChangelogIdentityFragmentTests(unittest.TestCase):
    """CHANGELOG 豁免面窄域复检 (F-202): 模式 1 (工具链旧根路径) 享账目
    append-only 豁免; 身份碎片 (私有工作区路径/本机用户名) 不享——
    公开仓账目里零容忍, 独立机检防再犯 (复审 H-1 实锤过叙述层回归)。"""

    def test_no_identity_fragments_in_changelog(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "CHANGELOG.md")
        hits = []
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                for pat in _IDENTITY_PATTERNS:
                    if pat.search(line):
                        hits.append(f"CHANGELOG.md:{i} ({pat.pattern})")
                        break
        self.assertEqual(
            hits, [],
            "CHANGELOG 出现身份碎片路径 (F-202 窄域钉, 账目豁免不含身份面):\n"
            + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
