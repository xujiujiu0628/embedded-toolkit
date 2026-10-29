"""F-235: gcc.toolchain 派发 — arm(缺省) / wch 两套工具链。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gcc_build  # noqa: E402

MACHINE = {
    "gcc_path": "/arm/bin",
    "wch_gcc_path": "/wch/bin",
    "make_exe": "/usr/bin/make",
}


class ResolveToolchainTests(unittest.TestCase):
    def test_default_is_arm(self):
        got = gcc_build.resolve_toolchain({}, MACHINE)
        self.assertEqual(got, {"kind": "arm", "bin_dir": "/arm/bin",
                               "prefix": "arm-none-eabi-"})

    def test_wch_uses_wch_key_and_prefix(self):
        got = gcc_build.resolve_toolchain({"toolchain": "wch"}, MACHINE)
        self.assertEqual(got, {"kind": "wch", "bin_dir": "/wch/bin",
                               "prefix": "riscv-wch-elf-"})

    def test_unknown_value_lists_legal_values(self):
        with self.assertRaises(ValueError) as ctx:
            gcc_build.resolve_toolchain({"toolchain": "riscv"}, MACHINE)
        msg = str(ctx.exception)
        self.assertIn("不在白名单", msg)
        self.assertIn("arm", msg)
        self.assertIn("wch", msg)

    def test_wch_missing_key_names_the_key(self):
        with self.assertRaises(ValueError) as ctx:
            gcc_build.resolve_toolchain({"toolchain": "wch"}, {"gcc_path": "/arm/bin"})
        self.assertIn("wch_gcc_path", str(ctx.exception))

    def test_arm_missing_key_keeps_legacy_wording(self):
        # 既有测试 test_gcc_build.py:164 断言 "gcc_path invalid" 子串, 不许改口径
        with self.assertRaises(ValueError) as ctx:
            gcc_build.resolve_toolchain({}, {})
        self.assertIn("gcc_path invalid", str(ctx.exception))


class ToolVarsTests(unittest.TestCase):
    def test_arm_injects_nothing(self):
        tc = {"kind": "arm", "bin_dir": "/arm/bin", "prefix": "arm-none-eabi-"}
        self.assertEqual(gcc_build._tool_vars(tc), [])

    def test_wch_injects_three_tools(self):
        tc = {"kind": "wch", "bin_dir": "/wch/bin", "prefix": "riscv-wch-elf-"}
        # 模块引用替换式 (F-184/GAP-F-9 钦定形态) —— 打桩 gcc_build.shutil.which
        # 会撞 test_stub_ratchet 全局打桩棘轮 (新增即红), 故替换模块引用。
        fake_shutil = mock.Mock(which=mock.Mock(return_value=None))
        with mock.patch.object(gcc_build, "shutil", fake_shutil):
            got = gcc_build._tool_vars(tc)
        self.assertEqual(len(got), 3)
        self.assertTrue(got[0].startswith("CC="))
        self.assertIn("riscv-wch-elf-gcc", got[0])
        self.assertTrue(got[1].startswith("OBJCOPY="))
        self.assertIn("riscv-wch-elf-objcopy", got[1])
        self.assertTrue(got[2].startswith("SIZE="))
        self.assertIn("riscv-wch-elf-size", got[2])


if __name__ == "__main__":
    unittest.main()
