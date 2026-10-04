r"""四审新发现三件的回归钉 (F-222)。

三件都是「上一轮说已修/已收口, 实际只做了一半」的形态——与 F-219 记的
「D4 改善真实但错配本体未修」同族:

| 项 | 上一轮账目怎么说 | 实际只做到 |
|---|---|---|
| D4 预算错配 | 「hardfault 层2 预算错配 已修复」 | 只做了显式化+超时可辨识; **错配本体在 `verify.py:1279` 的外层 `timeout=60`, 未动** |
| hw_lease meta(B8a) | 「meta 旁车竞态 已修复」 | 只修了截断写(撕裂); **解锁后无条件 `os.remove` 的误删窗口仍在** |
| save_skill_section | 未列 | 与 D3 **同一目标文件**的无锁读-改-写, 漏收 |

**共同病灶**: 账目按「我改了什么」写, 不按「缺陷的本体在哪」核——于是
"改善了一部分"被记成"已修复"。本组的存在意义是把这三处的**本体**钉住,
使下一次"部分修复"无法再冒充"已修复"。
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import hardfault  # noqa: E402
import hw_lease  # noqa: E402
import runtime_common  # noqa: E402
import verify  # noqa: E402


def _code_only(name: str) -> str:
    """剥掉注释与文档字符串, 只留可执行代码 (基于 ast, 不做文本手术)。

    四次教训逼出来的:
    1. 纯文本扫描会命中我自己写的**说明文字** -> 假红;
    2. 手写字符串扫描把字面量误判成注释起点 -> 切错函数体;
    3. 改用 tokenize 后 `" ".join` 抹平行结构 -> split 失配;
    4. 只取 `lineno`(语句**首行**)会丢掉多行调用的**续行**——
       `timeout=max(60, ...)` 写在 `subprocess.run(...)` 的续行上,
       于是断言"代码里没有该 timeout"而实际有。

    故按 `lineno..end_lineno` 取**整段**。注释与 docstring 本就不在语法树里。
    """
    import ast
    src = _src(name)
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    keep = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.stmt, ast.arg)) and hasattr(node, "lineno"):
            start = node.lineno
            end = getattr(node, "end_lineno", start) or start
            keep.update(range(start, end + 1))
    return "".join(lines[i - 1] for i in sorted(keep))


def _src(name):
    """读脚本原文(含注释)。形态钉请配 _code_only 使用。"""
    with open(os.path.join(ROOT, "scripts", name), encoding="utf-8") as f:
        return f.read()


class D4OuterBudgetCoversInnerTests(unittest.TestCase):
    """**D4 的本体**: verify spawn 层 2 时, 外层 timeout 必须罩过内层总预算。

    四审抓出: F-219 把 186s 显式化为 `OPENOCD_DIAG_BUDGET_S`, 却没动
    `verify.py:1279` 的 `timeout=60` —— 于是**在 verify 链路里层 2 必然
    被外层掐死在第 1 次尝试**, 3 次重试从未跑到第二遍。改善只惠及独立运行
    `hardfault.py` 的场景, 账目却写了「已修复」。
    """

    def test_verify_uses_inner_budget_not_literal_60(self):
        """形态钉: verify 的层 2 调用不得再有裸 `timeout=60`。"""
        src = _src("verify.py")
        self.assertIn("hardfault_budget_s()", src,
                      "verify 未引用层 2 预算常量 —— 外层 60s 会掐死内层 "
                      "186s 的重试(F-222 的错配本体)")
        # 剥注释再查: 注释里出现关键词不算"代码用了它"。
        # (首版未剥注释 → 断言在自己的说明文字里命中而假红。)
        code = _code_only("verify.py")
        self.assertIn("timeout=max(60, hardfault_budget_s())", code,
                      "层 2 spawn 的 timeout 未取层 2 预算")
        # 剥注释后不得再有裸 timeout=60 的层 2 调用
        seg = code.split("hf_cmd = [", 1)
        self.assertGreater(len(seg), 1, "未找到层 2 spawn 处")
        self.assertNotIn("timeout=60,", seg[1][:900],
                         "层 2 spawn 处仍有裸 timeout=60 —— 错配未修")

    def test_helper_reads_real_module_constant(self):
        """helper 必须真读到 hardfault.py 的常量, 不是硬编码副本。"""
        got = verify.hardfault_budget_s()
        self.assertEqual(
            got, hardfault.OPENOCD_DIAG_BUDGET_S,
            f"verify 读到 {got} != hardfault 声明 "
            f"{hardfault.OPENOCD_DIAG_BUDGET_S} —— 兜底副本已漂移")

    def test_helper_falls_back_without_crashing(self):
        """runpy 读不到时应退兜底值而非抛异常(门禁不能因读配置而崩)。"""
        real = verify.TOOLKIT_ROOT
        with mock.patch.object(verify, "TOOLKIT_ROOT",
                               os.path.join(ROOT, "nonexistent")):
            val = verify.hardfault_budget_s()
        self.assertEqual(val, 186, "读不到时应退兜底 186s")
        self.assertEqual(real, verify.TOOLKIT_ROOT)

    def test_budget_constant_is_still_186(self):
        """层 2 预算本身未动(本票只修外层错配)。"""
        self.assertEqual(hardfault.OPENOCD_DIAG_BUDGET_S, 186)


class B8aMetaDeleteOrderingTests(unittest.TestCase):
    """**B8a 本体**: meta 旁车必须在**解锁之前**删除。

    旧顺序 `unlock -> close -> remove` 留下交错窗口:
      A 解锁 -> B acquire 并写入新 meta -> A remove -> B 的旁车凭空消失
    后果与 D6 同型: `holder_info()` 读不到 meta 而把真实持有者报成
    「无人持有」——成因从"读到半截"变成"被整个删掉"。

    **修法不是不删, 而是改序**: B 只有在 A 解锁后才可能 acquire, 而 A 的
    删除已在解锁前完成 -> 不存在"A 删在 B 写之后"的交错。

    **为何仍须删**(首版曾想整行去掉, 被既有测试打回 5 例): `holder_info()`
    以「meta 存在」判定「有持有者」(`tests/test_hw_lease.py` 多处断言
    release 后旁车已清), 留着会让陈旧 meta 冒充活锁。该既有契约是对的,
    错的是删除时机。
    """

    def _release_calls(self):
        """release 内的 (行号, 被调函数名) 序列。"""
        import ast
        src = _src("hw_lease.py")
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "release")
        calls = []
        for c in ast.walk(fn):
            if isinstance(c, ast.Call):
                calls.append((c.lineno, ast.unparse(c.func)))
        return sorted(calls)

    def test_meta_removed_before_unlock(self):
        """**核心判据**: os.remove 的行号必须早于解锁。"""
        calls = self._release_calls()
        removes = [ln for ln, name in calls if name == "os.remove"]
        self.assertTrue(removes, "release 未删 meta —— 若确要改为不删, "
                                  "须先改 tests/test_hw_lease.py 的既有契约")
        unlocks = [ln for ln, name in calls if "unlock_byte" in name]
        self.assertTrue(unlocks, "未找到 _unlock_byte 调用")
        self.assertLess(
            min(removes), min(unlocks),
            f"meta 删除(行 {min(removes)}) 必须在解锁(行 {min(unlocks)}) "
            f"之前 —— 否则留有 'A 解锁 -> B 写新 meta -> A 删除' 的交错窗口")

    def test_lock_file_still_not_removed_either(self):
        """M-2 的锁本体留置论证不得被回退 (只删 meta, 不删锁文件)。"""
        import ast
        src = _src("hw_lease.py")
        removes = [ast.unparse(n) for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.Call)
                   and ast.unparse(n.func) == "os.remove"]
        self.assertTrue(removes, "meta 应仍被删除")
        self.assertNotIn("os.remove(lock_file)", removes,
                         "锁本体被删 —— 会引入 inode 交换窗口 (M-2 已论证)")

    def test_meta_cleared_after_release(self):
        """行为钉: release 后 holder_info 为空 (既有契约, 不得回退)。

        这是首版"整行删掉 os.remove"被打回 5 例的原因——陈旧 meta 冒充活锁。
        """
        lease = hw_lease.acquire(purpose="f222 probe")
        if not lease.get("ok"):
            self.skipTest("设备被占用, 跳过 (与既有测试同处置)")
        res = hw_lease.release(lease)
        self.assertTrue(res.get("ok"), f"release 失败: {res.get('error')}")
        info = hw_lease.holder_info()
        self.assertIsNone(info, f"release 后仍有持有者 meta: {info}")



class SaveSkillSectionLockTests(unittest.TestCase):
    """save_skill_section 与 D3 写**同一 config.json**, 必须共用同一把锁。"""

    def test_source_takes_file_lock(self):
        src = _src("runtime_common.py")
        body = src.split("def save_skill_section", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("with file_lock(file_path):", body,
                      "save_skill_section 未持锁 —— 与 D3 同目标文件的"
                      "丢更新竞态(两处各加各的锁等于没加)")

    def test_runtime_common_uses_shared_lock_from_wb_common(self):
        """锁必须来自 wb_common 单一来源, 不是各脚本各抄一份。"""
        src = _src("runtime_common.py")
        self.assertIn("from wb_common import file_lock", src,
                      "未从 wb_common 复用 file_lock —— 锁不共享则互斥失效")

    def test_still_preserves_corrupt_refusal(self):
        """F-020 契约不回归: 损坏时拒绝写回并返 None(加锁不得吞掉该行为)。"""
        import tempfile
        from runtime_common import JSONCorruptError
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "config.json")
            with open(cfg, "w", encoding="utf-8") as f:
                f.write("{ this is not json")
            with mock.patch.object(runtime_common, "load_json_strict",
                                   side_effect=JSONCorruptError("boom")):
                res = runtime_common.save_skill_section(cfg, "wb", {"a": 1})
        self.assertIsNone(res, "损坏时必须返 None(F-020 契约)")


if __name__ == "__main__":
    unittest.main()