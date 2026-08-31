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

    load_project_config 本身返回"某一段"(默认段名是 keil 遗留)；旧写法
    `load_project_config(ws).get("gcc")` 恒得 {} → 手工运行不带 --target
    即把工程 config 的 target 写回清空 (2026-08-30 button-toggle 实锤)。
    """

    def setUp(self):
        import tempfile
        from wb_runtime import save_json_file
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
        # 反证旧写法: 默认段(keil)在 gcc-only 配置下为空 → .get("gcc") 恒 {}
        from wb_runtime import load_project_config
        self.assertEqual(load_project_config(self.tmp).get("gcc", {}), {})


if __name__ == "__main__":
    unittest.main()
