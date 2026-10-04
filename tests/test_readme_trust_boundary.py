r"""README 信任边界声明的存在性钉 (F-219, L-3).

背景: `.workbench/config.json` 不只是数据——`gcc.project` 决定跑哪个
Makefile (可含任意 shell recipe)、`capture.sim.exe` 直接是任意可执行文件。
故把 verify / MCP `run_verify` 指向不受信工程 = 以调用者权限执行该工程作者
指定的任意命令。设备锁 / bounded argv / 参数白名单**都不覆盖这一条**。

本仓反复出现的病灶是"文档里的结论无声消失": F-218 那轮我在自己写的
"已脱敏"说明里复述了待脱敏串, SENSITIVE_FINDINGS 的"终验零残留"隔了两个月
才被发现不实。README 这一节若只靠人记, 同样会被某次重构顺手删掉而无痕。

故钉住它**存在且含关键要素**。钉声明的存在而非逐字文案——措辞可迭代,
"有没有说"不可迭代。删节/改名会使本测试转红, 届时或恢复或显式改写本测试
并记账 (与 test_version_single_source 同一处置纪律)。
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")

# 章节标题形态: 信任边界 (允许 "### ⚠️ 信任边界..." / "## 信任边界...")
_TRUST_HEADING_RE = re.compile(
    r"^#{2,4}\s*.*?信任边界", re.M)
# 必须点名的两个可执行决定键 —— 缺任一则该节退化成立泛谈
_REQUIRED_KEYS = ("gcc.project", "sim.exe")
# 必须出现的告警语义 (择一即可, 允许措辞迭代)
_REQUIRED_WARNINGS = ("不受信", "任意命令", "等价")


def _readme():
    with open(README, encoding="utf-8") as f:
        return f.read()


class ReadmeTrustBoundaryTests(unittest.TestCase):

    def test_trust_boundary_section_exists(self):
        """README 必须有信任边界章节。删掉即红。"""
        self.assertIsNotNone(
            _TRUST_HEADING_RE.search(_readme()),
            "README 缺「信任边界」章节 —— L-3 登记的文档项被删或改名。"
            "若确要移除, 须先撤销 config.json 的执行面语义并同步 CHANGELOG。")

    def test_section_names_both_execution_deciders(self):
        """该节必须点名两个真正的执行决定键, 而非泛谈'注意安全'。

        收紧到**机制表**而非整节正文: 变异实测发现整节正文里`gcc.project`
        有两处提及 (表格 + 规避段), 只删表格行本例会假绿——那是冗余提及
        掩盖了结构缺失。故此处直接定位 Markdown 表格行。
        """
        text = _readme()
        m = _TRUST_HEADING_RE.search(text)
        self.assertIsNotNone(m, "先过 test_trust_boundary_section_exists")
        body = text[m.end():]
        nxt = re.search(r"^#{1,4}\s", body, re.M)
        if nxt:
            body = body[:nxt.start()]
        # 只看表格行 (以 | 开头的行) —— 结构所在, 非叙述复述
        table_lines = [ln for ln in body.splitlines()
                       if ln.strip().startswith("|")]
        self.assertTrue(
            table_lines,
            "信任边界节缺机制表 —— 该节应以表格列出 config.json 哪些键"
            "决定执行什么; 纯叙述无法让读者逐项核对风险")
        table = "\n".join(table_lines)
        for key in _REQUIRED_KEYS:
            self.assertIn(
                key, table,
                f"信任边界机制表未列 {key} —— 它是 config.json 真正决定"
                f"执行什么的一环, 漏写则该节不足以让读者判断风险")

    def test_section_carries_explicit_warning(self):
        """必须有显式告警语义, 不能只是陈述机制。"""
        text = _readme()
        m = _TRUST_HEADING_RE.search(text)
        self.assertIsNotNone(m, "先过 test_trust_boundary_section_exists")
        body = text[m.end():]
        nxt = re.search(r"^#{1,4}\s", body, re.M)
        if nxt:
            body = body[:nxt.start()]
        self.assertTrue(
            any(w in body for w in _REQUIRED_WARNINGS),
            f"信任边界节缺显式告警语义 (须含其一: {_REQUIRED_WARNINGS})")


class ConfigExecSurfaceTests(unittest.TestCase):
    """反向钉: config.json 的执行面**仍在**——若上游收窄了执行面,
    README 该节的表述需同步降级。此钉防 README 拿 stale 措辞吓唬读者。"""

    def test_gcc_project_still_selects_makefile(self):
        path = os.path.join(ROOT, "scripts", "gcc_build.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertRegex(
            src, r'gcc_cfg\.get\("project"',
            "gcc_build 不再从 config 读 gcc.project —— README 信任边界节的"
            "机制陈述已过期, 须同步修订并记账")


if __name__ == "__main__":
    unittest.main()