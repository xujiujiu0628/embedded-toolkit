r"""F-109: SCB CFSR/HFSR 粘滞位"读后清除"回归钉。

背景 (审计 P3 推测项, 2026-09-10 真机取证结案):
  - CFSR(0xE000ED28)/HFSR(0xE000ED2C) 是 W1C 粘滞位, 置位后不自动消失。
  - hardfault.py 旧版只读不清 → 同一 halt 会话内第二次诊断会把上一次
    的陈旧位当新故障归因 (误诊路径)。
  - 真机取证 (xPack OpenOCD 0.12 + F103C8T6):
    T-A 复位后全 1 写"清除"读回 0——目标本就干净, 不构成置位证据;
    T-B mww 注入 UFSR 位被硬件拒绝 (写不进)——故障位只能由真故障置位;
    T-C1 制造真故障 (PC→0x0800ff00 已擦除 flash) 读得
         CFSR=0x00010000(HFSR 升级链 UNDEFINSTR) + HFSR=0x40000000(FORCED),
         粘滞坐实: 后续多次 halt 重复读到同值;
    T-C2 按位写 1 清除 (mww 0x00010000 / 0x40000000) → 读回 0x00000000,
         W1C 清除路径实测有效。
  - 结论: 工具侧"读→报告→W1C 清→复核 residual"; BFAR/MMFAR 普通 R/W
    不清 (VALID 位清后其值即失效)。固件 handler 不写清位——保位留现场。
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hardfault  # noqa: E402


def _mdw_lines(addr_hex, values):
    """按 OpenOCD 'mdw <addr> 1' 输出格式造多行 (每次读一行)。"""
    return "\n".join(f"0x{addr_hex:08x}: {v:08x}" for v in values)


class ClearSequenceInOpenocdCmdTests(unittest.TestCase):
    """取证的清除动作必须真实出现在 OpenOCD 命令序列里, 且顺序正确"""

    def _captured_cmd(self):
        calls = {}

        class _R:
            stdout = "SWD DPIDR 0x1ba01477\n" + _mdw_lines(0xE0000015, [0]) + \
                "pc (/32): 0x0800012a\n"
            stderr = ""

        def fake_run(cmd, **kw):
            calls["cmd"] = cmd
            return _R()

        with mock.patch.object(hardfault, "load_machine",
                               return_value={"openocd_exe": "openocd"}), \
                mock.patch.object(hardfault.subprocess, "run", fake_run):
            out = hardfault.run_openocd_diag()
        return calls["cmd"], out

    def test_cmd_contains_w1c_clear_after_first_reads(self):
        cmd, _ = self._captured_cmd()
        joined = "\n".join(cmd)
        # 两个故障寄存器都要: 首读 → 写全 1 清 → 复读 residual
        self.assertIn("mww 0xE000ED28 0xFFFFFFFF", joined)
        self.assertIn("mww 0xE000ED2C 0xFFFFFFFF", joined)
        # 顺序钉: 每个寄存器的 mww 在首 mdw 之后, 且其后还有第二次 mdw
        for addr in ("0xE000ED28", "0xE000ED2C"):
            first_read = cmd.index(f"mdw {addr} 1")
            clear = cmd.index(f"mww {addr} 0xFFFFFFFF")
            second_read = [i for i, c in enumerate(cmd)
                           if c == f"mdw {addr} 1"][-1]
            self.assertLess(first_read, clear,
                            f"{addr}: 必须读完再清 (诊断基于原始位)")
            self.assertLess(clear, second_read,
                            f"{addr}: 清后必须复读以取证 residual")
            self.assertEqual(len([i for i, c in enumerate(cmd)
                                   if c == f"mdw {addr} 1"]), 2)
        # BFAR/MMFAR 不列入清除 (普通 R/W, VALID 位清即失效)
        self.assertNotIn("mww 0xE000ED38 0xFFFFFFFF", joined)
        self.assertNotIn("mww 0xE000ED34 0xFFFFFFFF", joined)


class ResidualParsingTests(unittest.TestCase):
    """同址两次 mdw: 首值=诊断依据, 末值=residual"""

    def test_first_and_last_occurrence(self):
        raw = _mdw_lines(0xE000ED28, [0x00010000, 0x00000000]) + "\n" + \
              _mdw_lines(0xE000ED2C, [0x40000000, 0x00000000])
        self.assertEqual(hardfault.parse_mdw_value(raw, 0xE000ED28),
                         0x00010000, "诊断值必须取首读 (清除前)")
        vals = hardfault.parse_mdw_all_values(raw, 0xE000ED28)
        self.assertEqual(vals, [0x00010000, 0x00000000])
        self.assertEqual(hardfault.parse_mdw_all_values(raw, 0xE000ED2C),
                         [0x40000000, 0x00000000])

    def test_single_occurrence_gives_no_residual(self):
        # 旧输出/清位失败场景: 只有一次读 → residual 不可知, 不得虚报
        raw = _mdw_lines(0xE000ED28, [0x00010000])
        self.assertEqual(hardfault.parse_mdw_all_values(raw, 0xE000ED28),
                         [0x00010000])

    def test_parse_registers_exposes_residual_keys(self):
        raw = (_mdw_lines(0xE000ED28, [0x00010000, 0]) + "\n"
               + _mdw_lines(0xE000ED2C, [0x40000000, 0]))
        regs = hardfault.parse_registers(raw)
        self.assertEqual(regs["cfsr"], 0x00010000)
        self.assertEqual(regs["cfsr_residual"], 0)
        self.assertEqual(regs["hfsr"], 0x40000000)
        self.assertEqual(regs["hfsr_residual"], 0)

    def test_parse_registers_residual_absent_when_single_read(self):
        regs = hardfault.parse_registers(_mdw_lines(0xE000ED28, [0x1]))
        self.assertEqual(regs["cfsr"], 1)
        self.assertNotIn("cfsr_residual", regs,
                         "无二次读时不得凭空造 residual 键")


class StickyHygieneReportTests(unittest.TestCase):
    """JSON 输出必须携带 sticky_hygiene 结论 (消费方据此判卫生状态)"""

    def test_all_cleared(self):
        h = hardfault.sticky_hygiene({"cfsr": 0x10000, "cfsr_residual": 0,
                                      "hfsr": 0x40000000, "hfsr_residual": 0})
        self.assertTrue(h["cfsr"]["cleared"])
        self.assertTrue(h["hfsr"]["cleared"])
        self.assertEqual(h["cfsr"]["before"], "0x00010000")
        self.assertEqual(h["cfsr"]["after"], "0x00000000")

    def test_residual_nonzero_flagged(self):
        # 复核读到非 0 → 写路径异常/复位竞态, 必须如实标 False 而非隐藏
        h = hardfault.sticky_hygiene({"cfsr": 0x1, "cfsr_residual": 0x1,
                                      "hfsr": 0, "hfsr_residual": 0})
        self.assertFalse(h["cfsr"]["cleared"])

    def test_unknown_when_second_read_missing(self):
        h = hardfault.sticky_hygiene({"cfsr": 0x1})
        self.assertIsNone(h["cfsr"]["cleared"])
        self.assertIsNone(h["cfsr"]["after"])


if __name__ == "__main__":
    unittest.main()
