"""F-006 回归: gcc_build 的 import time 上移模块顶部 (2026-08-30 代管 Day 3).

修复前: import time 在 if __name__ == "__main__" 块内, main() 引用 time —
作为脚本运行正常, 但任何未来调用方 import gcc_build 再调 main() 即 NameError
(verify.py 走 subprocess 故未触发, 属埋雷)。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gcc_build  # noqa: E402


class ModuleImportSafetyTests(unittest.TestCase):
    def test_time_bound_at_module_level(self):
        # 修复前 False (time 仅在 __main__ 块内绑定), 被调用方 import 即埋雷
        self.assertTrue(hasattr(gcc_build, "time"))

    def test_main_importable(self):
        from gcc_build import main  # noqa: F401  引用本身不炸
        self.assertTrue(callable(main))


class WorkspaceDerivationTests(unittest.TestCase):
    """F-015 回归 (2026-08-30 主控实锤): 从 A 目录跑 --project 指到 B 工程,
    workspace 若不跟随 B, 日志与 gcc 段配置写回会造出 A/.workbench 伪工程。"""

    def test_project_explicit_workspace_absent_follows_project(self):
        from pathlib import Path
        w = gcc_build.resolve_workspace_mode(
            args_project="D:/proj/B/Makefile", args_workspace=None,
            workspace=Path("D:/toolkit"), project_dir=Path("D:/proj/B"))
        self.assertEqual(w, Path("D:/proj/B"))

    def test_explicit_workspace_always_wins(self):
        from pathlib import Path
        w = gcc_build.resolve_workspace_mode(
            args_project="D:/proj/B/Makefile", args_workspace="D:/ws",
            workspace=Path("D:/ws"), project_dir=Path("D:/proj/B"))
        self.assertEqual(w, Path("D:/ws"))

    def test_no_project_keeps_workspace(self):
        from pathlib import Path
        w = gcc_build.resolve_workspace_mode(
            args_project=None, args_workspace=None,
            workspace=Path("D:/ws"), project_dir=Path("D:/ws/gcc-pilot"))
        self.assertEqual(w, Path("D:/ws"))


class GccSectionLoadTests(unittest.TestCase):
    """F-017 回归: gcc_build 读工程配置必须用 skill="gcc" 段。

    load_project_config 本身返回"某一段"(默认段名 wb 是历史延续, 原 keil
    2026-08-28 中性化、2026-09-05 退役区拆 archive 后改 wb); 旧写法
    `load_project_config(ws).get("gcc")` 恒得 {} → 手工运行不带 --target
    即把工程 config 的 target 写回清空 (2026-08-30 button-toggle 实锤)。
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, ".workbench"), exist_ok=True)
        with open(os.path.join(self.tmp, ".workbench", "config.json"),
                  "w", encoding="utf-8") as f:
            f.write('{"builder":"gcc","gcc":{"project":"Makefile",'
                    '"target":"button-toggle"},"capture":{"backend":"rtt"}}')

    def test_gcc_section_read_correct(self):
        from wb_runtime import load_project_config
        cfg = load_project_config(self.tmp, skill="gcc")
        self.assertEqual(cfg.get("target"), "button-toggle")

    def test_old_pattern_proves_bug(self):
        # 反证旧写法: 默认段(wb, 历史延续)在 gcc-only 配置下为空 → .get("gcc") 恒 {}
        from wb_runtime import load_project_config
        self.assertEqual(load_project_config(self.tmp).get("gcc", {}), {})


class MakeTimingScaleTests(unittest.TestCase):
    """F-099 修复钉: gcc_build 的 timing_ms 必须是毫秒量级 (P2-4: 曾把秒
    直接当毫秒传入 make_timing, elapsed_ms 偏小 1000 倍)。性质断言: 真实
    耗时 >=0.2s 的操作, elapsed_ms 必须落在 [200, 60000] 而非 [0, 60]。"""

    def test_timing_ms_is_milliseconds_not_seconds(self):
        import time as _time
        from runtime_common import make_timing
        started_at = "2026-09-09T12:00:00+08:00"
        started_ts = _time.time()
        _time.sleep(0.25)   # 250ms — 秒口径会得 0, 毫秒口径得 ~250
        timing = make_timing(started_at, (_time.time() - started_ts) * 1000)
        self.assertGreaterEqual(timing["elapsed_ms"], 200,
                                "elapsed_ms 偏小 1000 倍 (秒当毫秒)")
        self.assertLess(timing["elapsed_ms"], 60000)

    def test_gcc_build_source_uses_ms_conversion(self):
        """静态钉 (F-159 AST 化): gcc_build.py 的 make_timing 调用必须带
        *1000 毫秒换算 — 旧文本匹配 "* 1000" 会随换行/空格/写法漂移假红假绿,
        AST 语义断言抗格式漂移 (行为钉见上例)。"""
        import ast
        import pathlib
        src_path = pathlib.Path(__file__).resolve().parent.parent / \
            "scripts" / "gcc_build.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and ((isinstance(n.func, ast.Attribute) and n.func.attr == "make_timing")
                      or (isinstance(n.func, ast.Name) and n.func.id == "make_timing"))]
        self.assertTrue(calls, "make_timing 调用消失?")

        def _has_ms_scale(node):
            return (isinstance(node, ast.BinOp)
                    and isinstance(node.op, ast.Mult)
                    and isinstance(node.right, ast.Constant)
                    and node.right.value == 1000)

        for call in calls:
            scaled = any(_has_ms_scale(node)
                         for arg in call.args
                         for node in ast.walk(arg))
            self.assertTrue(scaled,
                            "make_timing 调用缺毫秒换算 (*1000): "
                            f"line {call.lineno}")


if __name__ == "__main__":
    # F-125 (工单 P1-2): unittest.main() 必须在全部类定义之后 —— 旧位置在
    # MakeTimingScaleTests 之前, 单文件直跑时该类不被收集, F-099 回归钉形同虚设
    unittest.main()
