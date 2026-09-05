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

import hardfault  # noqa: E402  (F-054 后 import 期零 IO)


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
        # 工程存在但无 build//lst/: 行为与修复前一致 (返回旧默认路径, 空符号表有告警兜底)
        _mk_project(self.tmp)
        os.chdir(self.tmp)
        path = hardfault._default_map_path()
        self.assertTrue(path.endswith(os.path.join("lst", "blink.map")))

    def test_gcc_layout_map_in_build_preferred(self):
        # 插板终判回归: GCC 工程 map 在 build/ (adc-oled 实态), 必须被发现
        _mk_project(self.tmp)
        b = os.path.join(self.tmp, "build")
        os.makedirs(b)
        with open(os.path.join(b, "fw.map"), "w", encoding="utf-8") as f:
            f.write("stub")
        os.chdir(self.tmp)
        self.assertEqual(hardfault._default_map_path(),
                         os.path.join(b, "fw.map"))

    def test_build_beats_lst_when_both(self):
        _mk_project(self.tmp)
        for sub, name in (("build", "g.map"), ("lst", "k.map")):
            d = os.path.join(self.tmp, sub)
            os.makedirs(d)
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write("stub")
        os.chdir(self.tmp)
        self.assertTrue(hardfault._default_map_path().endswith("g.map"))

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


GCC_MAP_FIXTURE = """\
Memory Configuration

Name             Origin             Length             Attributes
FLASH            0x08000000         0x00020000         xr

Linker script and memory map

.text           0x0800010c     0x1a14
                0x0800010c                . = ALIGN (0x4)
 .text          0x0800010c       0x40 crtbegin.o
                0x0800014c                strlen
 .text          0x08000180       0x54 build/main.o
                0x08000181                main
                0x20000100                g_oled
"""


class GccMapParseResolveTests(unittest.TestCase):
    """F-005 第二/三层 (插板终判实测): ld map 版式解析 + size=0 最近前导兜底。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.map = os.path.join(self.tmp, "fw.map")
        with open(self.map, "w", encoding="utf-8") as f:
            f.write(GCC_MAP_FIXTURE)

    def test_gcc_map_parses_symbols_skips_pseudo(self):
        syms = {s["name"]: s for s in hardfault.parse_map_symbols(self.map)}
        self.assertIn("strlen", syms)
        self.assertIn("main", syms)
        self.assertIn("g_oled", syms)
        self.assertNotIn(".", syms)  # . = ALIGN 伪行不入库
        self.assertEqual(syms["main"]["addr"], 0x08000181)

    def test_resolve_gcc_zero_size_fallback(self):
        syms = hardfault.parse_map_symbols(self.map)
        r = hardfault.resolve_address(0x0800014C, syms)
        self.assertIsNotNone(r)
        self.assertEqual(r["name"], "strlen")
        r2 = hardfault.resolve_address(0x08000150, syms)  # 函数中段 → 最近前导
        self.assertEqual(r2["name"], "strlen")
        self.assertEqual(r2["offset"], 4)
        self.assertIsNone(hardfault.resolve_address(0x00000010, syms))  # 低于一切

    def test_armcc_interval_still_preferred(self):
        # 有 size 的 ARMCC 符号仍走区间主路径 (语义不变)
        syms = [{"name": "fn", "addr": 0x100, "type": "Thumb Code",
                 "size": 8, "object": "a.o(.text)"},
                {"name": "bare", "addr": 0x0F0, "type": "", "size": 0,
                 "object": ""}]
        r = hardfault.resolve_address(0x104, syms)
        self.assertEqual(r["name"], "fn")


class MapDegradationNoteTests(unittest.TestCase):
    """换回复核补丁 (主控): 符号表为空必须告警, 不得静默降级。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_empty_symbols_missing_file_warns(self):
        ghost = os.path.join(self.tmp, "nope.map")
        note = hardfault._map_degradation_note(ghost, [])
        self.assertIsNotNone(note)
        self.assertIn("文件不存在", note)
        self.assertIn(ghost.replace("\\", "/"), note.replace("\\", "/"))

    def test_empty_symbols_existing_file_warns(self):
        p = os.path.join(self.tmp, "empty.map")
        with open(p, "w", encoding="utf-8") as f:
            f.write("Archive member\n")  # 存在但解析不出全局符号
        note = hardfault._map_degradation_note(p, hardfault.parse_map_symbols(p))
        self.assertIsNotNone(note)
        self.assertIn("无全局符号", note)

    def test_nonempty_symbols_no_note(self):
        self.assertIsNone(hardfault._map_degradation_note("whatever.map",
                                                          [{"name": "main"}]))


if __name__ == "__main__":
    unittest.main()
