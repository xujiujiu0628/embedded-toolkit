r"""F-245: hardfault 的符号表解析 / 诊断文本 / 捕获文本读取补测。

## 覆盖对象

`scripts/hardfault.py` 此前 87% 覆盖（2026-11-02 实测）：`parse_map_symbols`
的 GCC ld 与 ARMCC 两种版式、`diagnose` 的 BFAR/MMFAR/PC 分支、
`_read_fault_text` 的 stdin/文件/不可读三态、`_default_map_path` 的
build/lst/兜底三级未执行。
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hardfault  # noqa: E402

GCC_MAP = """\
                0x08000000                main
                0x08000100                foo
                0x08000200                _etext
"""

ARMCC_MAP = """\
Global Symbols
    Symbol Name                              Value     Ov Type        Size  Object(Section)
    main                                     0x08000309   Thumb Code   120  main.o(.text)
    foo                                      0x08000400   Thumb Code    32  foo.o(.text)
"""


class ParseMapTests(unittest.TestCase):
    def test_missing_file(self):
        self.assertEqual(hardfault.parse_map_symbols("no-such.map"), [])

    def test_gcc_ld_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fw.map")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(GCC_MAP)
            symbols = hardfault.parse_map_symbols(path)
        names = [s["name"] for s in symbols]
        self.assertIn("main", names)
        self.assertIn("foo", names)
        self.assertEqual(symbols[0]["size"], 0)

    def test_armcc_global_symbols_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fw.map")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(ARMCC_MAP)
            symbols = hardfault.parse_map_symbols(path)
        by_name = {s["name"]: s for s in symbols}
        self.assertEqual(by_name["main"]["addr"], 0x08000309)
        self.assertEqual(by_name["main"]["size"], 120)
        self.assertEqual(by_name["foo"]["object"], "foo.o(.text)")


class DiagnoseTests(unittest.TestCase):
    def test_bfar_mmfar_and_pc(self):
        regs = {"pc": 0x08000100, "bfar": 0x20000000, "mmfar": 0x40000000,
                "cfsr": 0, "hfsr": 0x40000000}
        symbols = [{"name": "main", "addr": 0x08000000, "size": 0x200}]
        text = hardfault.diagnose(regs, symbols)
        self.assertIn("BFAR=0x20000000", text)
        self.assertIn("MMFAR=0x40000000", text)
        self.assertIn("PC=0x08000100 → main+256", text)

    def test_pc_without_symbol(self):
        text = hardfault.diagnose({"pc": 0x08000100, "cfsr": 0, "hfsr": 0}, [])
        self.assertIn("no matching symbol", text)


class ReadFaultTextTests(unittest.TestCase):
    def test_stdin(self):
        old = sys.stdin
        sys.stdin = io.StringIO("[HF] PC=0800012A LR=08000200")
        try:
            self.assertIn("[HF]", hardfault._read_fault_text("-"))
        finally:
            sys.stdin = old

    def test_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cap.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("hello")
            self.assertEqual(hardfault._read_fault_text(path), "hello")

    def test_unreadable_warns(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(
                hardfault._read_fault_text(os.path.join(tempfile.gettempdir(), "no-cap.txt")),
                "")
        self.assertIn("不可读", err.getvalue())


class DefaultMapPathTests(unittest.TestCase):
    def test_build_dir_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "build"))
            with open(os.path.join(tmp, "build", "fw.map"), "w", encoding="utf-8") as fh:
                fh.write(GCC_MAP)
            with mock.patch.object(hardfault, "find_project_root", return_value=tmp):
                path = hardfault._default_map_path()
        self.assertTrue(path.endswith("fw.map"))
        self.assertIn("build", path)

    def test_lst_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "lst"))
            with open(os.path.join(tmp, "lst", "fw.map"), "w", encoding="utf-8") as fh:
                fh.write(GCC_MAP)
            with mock.patch.object(hardfault, "find_project_root", return_value=tmp):
                path = hardfault._default_map_path()
        self.assertIn("lst", path)

    def test_no_project_uses_legacy_fallback(self):
        with mock.patch.object(hardfault, "find_project_root", return_value=None):
            path = hardfault._default_map_path()
        self.assertTrue(path.endswith("blink.map"))


if __name__ == "__main__":
    unittest.main()
