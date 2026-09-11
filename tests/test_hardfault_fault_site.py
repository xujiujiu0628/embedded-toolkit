"""F-116 (B1 复审处置) 回归: 层 1 现场行解析 + 模板契约 + 真编译器探针.

fresh-checker 审计 F-115 判 H-1: handler 自旋场景 live PC 恒指处理链,
"resolved.pc=main+670" 是最近前导符号兜底误归因——真实故障点只在层 1
RTT 的 [HF] PC=/LR= 行。本文件钉修复面:
  1. parse_hf_site 纯函数 (格式容错/取首命中/大小写)
  2. 模板契约静态钉 (marker 串/去 static/BFAR VALID 门控/浮点禁区)
  3. arm-none-eabi-gcc 可用时真编译 -c (不可用 skip 并如实, M-2 两档)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hardfault  # noqa: E402  (F-054 后 import 期零 IO)

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "templates", "hardfault_rtt.c")


class ParseHfSiteTests(unittest.TestCase):
    """F-116/H-1: [HF] PC=/LR= 行提取 (层 2 真实故障点入口)"""

    def test_canonical_line(self):
        site = hardfault.parse_hf_site(
            "x\r\n=== HARDFAULT ===\r\n"
            "[HF] CFSR=00010400 HFSR=40000000\r\n"
            "[HF] PC=0800100A LR=08001545\r\n")
        self.assertEqual(site, {"pc": 0x0800100A, "lr": 0x08001545})

    def test_lowercase_hex_accepted(self):
        site = hardfault.parse_hf_site("[HF] PC=0800abcd LR=0800ffff")
        self.assertEqual((site["pc"], site["lr"]), (0x0800ABCD, 0x0800FFFF))

    def test_first_hit_wins(self):
        # 多命中=病态输入, 取先者如实 (docstring 契约)
        site = hardfault.parse_hf_site(
            "[HF] PC=08001001 LR=08001002\n[HF] PC=08002001 LR=08002002")
        self.assertEqual(site["pc"], 0x08001001)

    def test_absent_returns_none(self):
        self.assertIsNone(hardfault.parse_hf_site("no fault here"))
        self.assertIsNone(hardfault.parse_hf_site(""))
        self.assertIsNone(hardfault.parse_hf_site(None))

    def test_malformed_hex_rejected(self):
        # 位数不对/含非 hex 字符不得半信半解
        self.assertIsNone(hardfault.parse_hf_site("[HF] PC=080010 LR=080015"))
        self.assertIsNone(hardfault.parse_hf_site("[HF] PC=0800ZZZZ LR=08001545"))

    def test_semihosting_era_line_compat(self):
        # blink semihosting 版格式 "[HF] PC=... LR=..." 同构 → 无需特判;
        # 无该行 (旧 printf 版) 返回 None, 不报错 (向后兼容)
        self.assertIsNone(hardfault.parse_hf_site(
            "CFSR=0x00000400 HFSR=0x40000000\nPC=0x0800012a\n"))


class TemplateContractTests(unittest.TestCase):
    """模板静态契约钉 (M-2 第一档; 行为由真机验收背书)"""

    @classmethod
    def setUpClass(cls):
        with open(TEMPLATE, encoding="utf-8") as f:
            cls.src = f.read()

    def test_marker_contract_strings_present(self):
        self.assertIn("=== HARDFAULT ===", self.src)
        self.assertIn('"[HF] PC="', self.src)
        self.assertIn('" LR="', self.src)

    def test_handler_body_non_static(self):
        # F-116/H-1: 进 map 全局符号, live PC 不再被兜底吞成 main+N
        m = re.search(r'^(?:__attribute__\(\(used\)\)\s*\n)?void wb_hardfault_body',
                      self.src, re.M)
        self.assertIsNotNone(m, "wb_hardfault_body 须非 static 且带 used")
        self.assertNotIn("static void _hardfault_body", self.src)

    def test_bfar_valid_gating(self):
        # L-4: BFAR/MMFAR 按 VALID 位标注, 无效值不再伪装地址
        self.assertIn("(1UL << 15)", self.src)   # BFARVALID
        self.assertIn("(1UL << 7)", self.src)    # MMARVALID
        self.assertIn("INVALID", self.src)

    def test_no_float_printf_nano_trap(self):
        # nano.specs 浮点教训: 模板 CODE 不得经 printf/%f 路径
        # (注释允许提及——契约文档要解释为什么不用)
        code = "\n".join(ln for ln in self.src.splitlines()
                         if not re.match(r"\s*[\*/]", ln))
        self.assertNotIn("printf(", code)
        self.assertNotIn("%f", code)

    def test_no_sticky_clear_in_firmware(self):
        # F-109 分工: 保位留证据, 清位归工具
        self.assertNotIn("mww", self.src)
        self.assertNotIn("= 0xFFFFFFFF", self.src)

    def test_pure_ascii_comments_per_spec(self):
        # spec §3.1 纯 ASCII (工具链中立 + ARMCC 时代遗产, ASCII-only 教训
        # 源自 memory/feedback-embedded-arch-implementation)
        bad = [(i, ln) for i, ln in enumerate(self.src.splitlines(), 1)
               if any(ord(c) > 127 for c in ln)]
        self.assertEqual(bad, [], "模板须纯 ASCII (F-116/M-1)")


class TemplateCompileProbeTests(unittest.TestCase):
    """M-2 第二档: 真编译器探针 (CI syntax-smoke job 有 arm-gcc; 本机有则跑)。

    用桩头隔离 RTT 依赖——契约验证的是模板自身语法/属性正确,
    不测 vendor RTT。编译器不可得如实 skip (不假绿)。"""

    STUB = ("typedef unsigned SEGGER_RTT_BufferIndex;  /* placeholder */\n"
            "unsigned SEGGER_RTT_Write(unsigned BufferIndex,\n"
            "                          const void* pBuffer, unsigned NumBytes);\n"
            "unsigned SEGGER_RTT_WriteString(unsigned BufferIndex,\n"
            "                                const char* s);\n")

    def setUp(self):
        self.gcc = shutil.which("arm-none-eabi-gcc")
        if not self.gcc:
            self.skipTest("arm-none-eabi-gcc 不在 PATH (真机编译由工程构建背书)")

    def test_compile_clean(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, "SEGGER_RTT.h"), "w") as f:
            f.write(self.STUB)
        r = subprocess.run(
            [self.gcc, "-c", "-mcpu=cortex-m3", "-mthumb", "-Os",
             "-Wall", "-Wextra", "-std=c99",
             "-I", tmp, TEMPLATE, "-o", os.path.join(tmp, "hf.o")],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertEqual(r.stderr.strip(), "", "零告警纪律")


if __name__ == "__main__":
    unittest.main()
