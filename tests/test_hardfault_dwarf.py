"""hardfault.py 的 DWARF 行号补全（`.map` 只给函数名，`.elf` 才给行）。

## 覆盖对象

- `addr2line_lookup`: 输出解析、`??` 视为未命中、任何异常都返回 None；
- `attach_dwarf`: 只对合法 flash 地址补键，键名 `<reg>_dwarf`；
- `_default_elf_path`: 与 `.map` 同名同目录的 `.elf`。

## 纪律

DWARF 是**可选增强**：工具缺席、ELF 缺席、ELF 没带 `-g` 都必须安静返回
None，绝不能让诊断器因为"没有行号"而失败或编造行号。`??` 落到结果里
比缺键更有害——读的人会以为那就是源码位置。
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hardfault  # noqa: E402


def _proc(stdout):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=0)


class Addr2LineLookupTests(unittest.TestCase):
    def test_missing_elf_returns_none(self):
        self.assertIsNone(hardfault.addr2line_lookup("Z:/nope.elf", 0x08001000))

    def test_parses_two_line_output(self):
        with tempfile.NamedTemporaryFile(suffix=".elf", delete=False) as fh:
            elf = fh.name
        try:
            with mock.patch.object(hardfault.subprocess, "run",
                                   return_value=_proc("main\nUser/main.c:182\n")):
                hit = hardfault.addr2line_lookup(elf, 0x080010E8, tool="addr2line")
        finally:
            os.remove(elf)
        self.assertEqual(hit["function"], "main")
        self.assertEqual(hit["location"], "User/main.c:182")

    def test_backslashes_normalized(self):
        with tempfile.NamedTemporaryFile(suffix=".elf", delete=False) as fh:
            elf = fh.name
        try:
            with mock.patch.object(hardfault.subprocess, "run",
                                   return_value=_proc("f\nD:\\proj\\a.c:7\n")):
                hit = hardfault.addr2line_lookup(elf, 0x08000000, tool="addr2line")
        finally:
            os.remove(elf)
        self.assertEqual(hit["location"], "D:/proj/a.c:7")

    def test_unknown_symbol_is_miss_not_garbage(self):
        with tempfile.NamedTemporaryFile(suffix=".elf", delete=False) as fh:
            elf = fh.name
        try:
            with mock.patch.object(hardfault.subprocess, "run",
                                   return_value=_proc("??\n??:?\n")):
                self.assertIsNone(
                    hardfault.addr2line_lookup(elf, 0xDEADBEEF, tool="addr2line"))
        finally:
            os.remove(elf)

    def test_subprocess_failure_is_quiet(self):
        with tempfile.NamedTemporaryFile(suffix=".elf", delete=False) as fh:
            elf = fh.name
        try:
            with mock.patch.object(hardfault.subprocess, "run",
                                   side_effect=OSError("no tool")):
                self.assertIsNone(
                    hardfault.addr2line_lookup(elf, 0x08000000, tool="addr2line"))
        finally:
            os.remove(elf)


class AttachDwarfTests(unittest.TestCase):
    def test_attaches_for_mapped_addresses_only(self):
        # 与既有 resolve_address 同一门槛: <= 0x08000000 视为不可解析
        site = {"pc": 0x08001234, "lr": 0x00000010}
        fault_site = {"pc": "0x08001234", "lr": "0x00000010"}

        def _fake(_elf, addr, _tool=None):
            return {"function": "f", "location": "a.c:1"}

        with mock.patch.object(hardfault, "addr2line_lookup", side_effect=_fake):
            hardfault.attach_dwarf(fault_site, site, "x.elf", "addr2line")
        self.assertIn("pc_dwarf", fault_site)
        self.assertNotIn("lr_dwarf", fault_site)

    def test_no_hit_leaves_keys_absent(self):
        site = {"pc": 0x08001234, "lr": 0x08005678}
        fault_site = {"pc": "0x08001234", "lr": "0x08005678"}
        with mock.patch.object(hardfault, "addr2line_lookup", return_value=None):
            hardfault.attach_dwarf(fault_site, site, "x.elf", "addr2line")
        self.assertEqual(set(fault_site), {"pc", "lr"})


class DefaultElfPathTests(unittest.TestCase):
    def test_sibling_elf_found(self):
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "fw.map")
            open(mp, "w").close()
            open(os.path.join(d, "fw.elf"), "w").close()
            self.assertEqual(hardfault._default_elf_path(mp),
                             os.path.join(d, "fw.elf"))

    def test_absent_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "fw.map")
            open(mp, "w").close()
            self.assertIsNone(hardfault._default_elf_path(mp))


if __name__ == "__main__":
    unittest.main()
