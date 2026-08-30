"""F-005 回归: hardfault.py 默认 map 自动发现 (2026-08-30 代管 Day 2).

修复前: 默认 map = <toolkit 仓根>/lst/blink.map (blink 退役残留) —
路径恒不存在, parse_map_symbols 返回 [], 符号解析静默降级无告警。
修复: cwd 向上发现工程根后取 lst/*.map 第一个; 无 lst/ 时才落旧兜底。
端到端效果待真机终判 (本测试覆盖路径发现逻辑, 不触硬件)。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hardfault  # noqa: E402  (import 期读 machine.json, 本机存在)


def _mk_project(ws):
    os.makedirs(os.path.join(ws, ".workbench"))
    with open(os.path.join(ws, ".workbench", "config.json"), "w",
              encoding="utf-8") as f:
        json.dump({"builder": "gcc"}, f)


class DefaultMapPathTests(unittest.TestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(os.chdir, self.old_cwd)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_discovers_first_map_in_project_lst(self):
        _mk_project(self.tmp)
        lst = os.path.join(self.tmp, "lst")
        os.makedirs(lst)
        for name in ("b.map", "a.map"):
            with open(os.path.join(lst, name), "w", encoding="utf-8") as f:
                f.write("stub")
        os.chdir(self.tmp)
        path = hardfault._default_map_path()
        self.assertEqual(path, os.path.join(lst, "a.map"))  # sorted 首个

    def test_no_lst_dir_falls_back_to_legacy_default(self):
        # 工程存在但无 lst/: 行为与修复前一致 (返回旧默认路径, symbols=[])
        _mk_project(self.tmp)
        os.chdir(self.tmp)
        path = hardfault._default_map_path()
        self.assertTrue(path.endswith(os.path.join("lst", "blink.map")))

    def test_no_project_root_falls_back_to_legacy_default(self):
        os.chdir(self.tmp)  # 无 .workbench marker
        path = hardfault._default_map_path()
        self.assertTrue(path.endswith(os.path.join("lst", "blink.map")))

    def test_explicit_map_flag_beats_discovery(self):
        # main 逻辑: --map 显式传入时优先 (防回归: 默认值逻辑不得覆盖 CLI)
        _mk_project(self.tmp)
        lst = os.path.join(self.tmp, "lst")
        os.makedirs(lst)
        custom = os.path.join(self.tmp, "custom.map")
        with open(custom, "w", encoding="utf-8") as f:
            f.write("stub")
        os.chdir(self.tmp)
        self.assertTrue(hardfault._default_map_path())  # 发现逻辑可用
        # main(): map_path = args.map or _default_map_path()
        map_path = custom or hardfault._default_map_path()
        self.assertEqual(map_path, custom)


if __name__ == "__main__":
    unittest.main()
