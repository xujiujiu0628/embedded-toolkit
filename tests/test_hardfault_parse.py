r"""hardfault 解析层回归 (F-081) — 失败归因链的主体补到可测。

背景: 2026-09-08 coverage 实测 hardfault.py 300 语句仅 27% —— 它是闭环
失败归因 (Step 4b) 的诊断主体, 且核心解析/分类全是纯函数, 测试成本极低。
只测纯函数与文件解析 (不触硬件, run_openocd_diag/main 不在范围):
  parse_reg_value / parse_mdw_value / parse_registers — OpenOCD 文本 → 寄存器表
  decode_bits / classify_fault — CFSR/HFSR 位域 → 故障分类 (含 no_fault 语义)
  parse_map_symbols — GCC ld map / ARMCC map 双版式 (含伪行过滤)
  resolve_address — 区间匹配 + GCC 无 size 时的最近前导符号兜底 (F-005)
  classify_address_range — F103 地址空间分类 (含空指针区间)

期望值取自 RM0008/Cortex-M3 TRM 的 SCB 寄存器定义 + 2026-09-08 实跑。
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hardfault  # noqa: E402


class ParseRegValueTests(unittest.TestCase):

    def test_openocd_reg_line_format(self):
        text = "pc (/32): 0x0800012a\nlr (/32): 0x08000abc"
        self.assertEqual(hardfault.parse_reg_value(text, "pc"), 0x0800012A)
        self.assertEqual(hardfault.parse_reg_value(text, "lr"), 0x08000ABC)

    def test_reg_name_must_match_whole_token(self):
        # "sp" 不得误吸 "msp" 行 (parse_registers 同时查两者)
        text = "msp (/32): 0x20005000\nsp (/32): 0x20004f00"
        self.assertEqual(hardfault.parse_reg_value(text, "sp"), 0x20004F00)
        self.assertEqual(hardfault.parse_reg_value(text, "msp"), 0x20005000)

    def test_missing_register_returns_none(self):
        self.assertIsNone(hardfault.parse_reg_value("r0 (/32): 0x0\n", "pc"))


class ParseMdwValueTests(unittest.TestCase):

    def test_scb_register_line(self):
        text = "0xe000ed28: 00020000"
        self.assertEqual(
            hardfault.parse_mdw_value(text, 0xE000ED28), 0x00020000)

    def test_wrong_address_returns_none(self):
        self.assertIsNone(hardfault.parse_mdw_value("0xe000ed28: 0", 0xE000ED2C))


class ParseRegistersTests(unittest.TestCase):

    def test_full_openocd_dump(self):
        dump = (
            "pc (/32): 0x08001234\n"
            "lr (/32): 0x08002345\n"
            "sp (/32): 0x20004ff0\n"
            "xpsr (/32): 0x01000000\n"
            "msp (/32): 0x20005000\n"
            "psp (/32): 0x00000000\n"
            "r0 (/32): 0x00000000\n"
            "r1 (/32): 0x00000001\n"
            "0xe000ed28: 00010002\n"   # CFSR: BusFault PRECISERR + BFARVALID
            "0xe000ed2c: 40000000\n"   # HFSR: FORCED
            "0xe000ed38: 20000010\n"   # BFAR: 非法 SRAM 地址
            "0xe000ed34: 00000000\n"   # MMFAR
        )
        regs = hardfault.parse_registers(dump)
        self.assertEqual(regs["pc"], 0x08001234)
        self.assertEqual(regs["cfsr"], 0x00010002)
        self.assertEqual(regs["hfsr"], 0x40000000)
        self.assertEqual(regs["bfar"], 0x20000010)
        self.assertEqual(regs["mmfar"], 0x00000000)


class ClassifyFaultTests(unittest.TestCase):

    def test_no_fault_when_all_status_registers_zero(self):
        """2026-08-12 修复语义: SCB 全零 = 卡死/被暂停, 不得报 HardFault"""
        verdict = hardfault.classify_fault({"cfsr": 0, "hfsr": 0})
        self.assertEqual(verdict["primary"], "no_fault")

    def test_forced_busfault_precise_with_valid_bfar(self):
        # CFSR = BFSR.PRECISERR(bit9) | BFARVALID(bit15); HFSR.FORCED(bit30)
        regs = {"cfsr": (1 << 9) | (1 << 15), "hfsr": (1 << 30)}
        verdict = hardfault.classify_fault(regs)
        self.assertEqual(verdict["primary"], "BusFault (PRECISERR)")
        self.assertIn("bfsr_preciserr", verdict["cfsr_bits"])
        self.assertIn("hfsr_forced", verdict["hfsr_bits"])

    def test_forced_usagefault_invstate(self):
        # CFSR = UFSR.INVSTATE(bit17); HFSR.FORCED
        regs = {"cfsr": 1 << 17, "hfsr": 1 << 30}
        self.assertEqual(
            hardfault.classify_fault(regs)["primary"],
            "UsageFault (INVSTATE)")

    def test_forced_memmanage_iaccviol(self):
        regs = {"cfsr": 1 << 0, "hfsr": 1 << 30}
        self.assertEqual(
            hardfault.classify_fault(regs)["primary"],
            "MemManage (IACCVIOL)")

    def test_busfault_priority_over_usagefault_when_both_set(self):
        # BFSR 与 UFSR 同置: 代码 if bfsr / elif ufsr — BusFault 优先
        regs = {"cfsr": (1 << 9) | (1 << 17), "hfsr": 1 << 30}
        self.assertEqual(
            hardfault.classify_fault(regs)["primary"],
            "BusFault (PRECISERR)")

    def test_debugevent_and_vecttbl_branches(self):
        self.assertEqual(
            hardfault.classify_fault({"cfsr": 0, "hfsr": 1 << 31})["primary"],
            "DebugEvent (BKPT without debugger?)")
        self.assertEqual(
            hardfault.classify_fault({"cfsr": 0, "hfsr": 1 << 1})["primary"],
            "VectorTable (bad VTOR/boot config)")

    def test_scrambled_bits_fall_through_to_raw_dump(self):
        # 有非零 SCB 位但都不构成已知主因 → 原样落 HFSR/CFSR 值, 不装懂
        verdict = hardfault.classify_fault({"cfsr": 1 << 5, "hfsr": 0})
        self.assertEqual(
            verdict["primary"], "HardFault (HFSR=0x00000000, CFSR=0x00000020)")


def _write_gcc_map(path: str):
    """GCC ld map 版式: 缩进的 `0xADDR name` 两列 + 伪行 (F-005 实测版式)"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "Memory Configuration\n\n"
            "Linker script and memory map\n"
            ".text           0x08000000     0x1234\n"
            "                0x08000000        main\n"
            "                0x08000100        fault_handler\n"
            "                0x08000200        . = ALIGN(0x4)\n"
            "                0x08000200        0x1234 deadbeef_section\n"
            "                0x08000200        _sdata\n"
            " *(.text*)\n"
        )


class MapSymbolTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gcc_ld_map_layout_parsed_with_pseudo_lines_filtered(self):
        path = os.path.join(self.tmp, "firmware.map")
        _write_gcc_map(path)
        symbols = hardfault.parse_map_symbols(path)
        names = [s["name"] for s in symbols]
        self.assertEqual(names, ["main", "fault_handler", "_sdata"])
        self.assertEqual(symbols[0]["addr"], 0x08000000)
        # GCC map 无 size → 置 0 (schema 兼容)
        self.assertEqual(symbols[0]["size"], 0)

    def test_missing_map_returns_empty(self):
        self.assertEqual(
            hardfault.parse_map_symbols(os.path.join(self.tmp, "no.map")), [])

    def test_empty_symbols_degradation_note(self):
        path = os.path.join(self.tmp, "no.map")
        note = hardfault._map_degradation_note(path, [])
        self.assertIn("文件不存在", note)
        self.assertIn("F-005", note)
        self.assertIsNone(
            hardfault._map_degradation_note(path, [{"name": "main"}]))


class ResolveAddressTests(unittest.TestCase):

    @unittest.expectedFailure
    def test_range_match_prefers_smallest_containing_symbol(self):
        """F-081 发现登记: resolve_address 注释写"优先匹配小函数（更精确）"，
        实现却是 `size > best_size` 选最大包含符号 — 注释与实现矛盾。
        本断言按注释意图写（嵌套场景 PC 落在大函数内的小 helper 应报 helper），
        修复为独立 commit (F-082)。"""
        symbols = [
            {"name": "big", "addr": 0x08000000, "size": 0x1000},
            {"name": "small", "addr": 0x08000100, "size": 0x10},
        ]
        hit = hardfault.resolve_address(0x08000108, symbols)
        self.assertEqual(hit, {"name": "small", "offset": 8, "size": 0x10})

    def test_gcc_sizeless_symbols_fall_back_to_leading_symbol(self):
        """F-005 兜底: GCC map 无 size → 区间匹配恒空, 取最近前导符号"""
        symbols = [
            {"name": "main", "addr": 0x08000000, "size": 0},
            {"name": "fault_handler", "addr": 0x08000100, "size": 0},
        ]
        hit = hardfault.resolve_address(0x08000108, symbols)
        self.assertEqual(hit, {"name": "fault_handler", "offset": 8, "size": 0})

    def test_address_below_all_symbols_returns_none(self):
        symbols = [{"name": "main", "addr": 0x08000100, "size": 0x100}]
        self.assertIsNone(hardfault.resolve_address(0x08000050, symbols))


class ClassifyAddressRangeTests(unittest.TestCase):

    def test_f103_memory_map_regions(self):
        cases = {
            0x08000000: "Flash (code/const)",
            0x0800FFFF: "Flash (code/const)",
            0x20000000: "SRAM (data/stack)",
            0x20004FFF: "SRAM (data/stack)",
            0x40010800: "Peripheral bus (APB/AHB)",   # GPIOA
            0xE000ED28: "Cortex-M3 private (SCB/NVIC/SysTick)",  # CFSR
            0x00000000: "Low memory (null pointer?)",
            0x60000000: "Unknown",
        }
        for addr, expect in cases.items():
            with self.subTest(addr=hex(addr)):
                self.assertEqual(hardfault.classify_address_range(addr), expect)


if __name__ == "__main__":
    unittest.main()
