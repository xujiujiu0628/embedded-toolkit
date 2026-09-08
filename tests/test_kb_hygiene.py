r"""知识库数据一致性校验 (F-083) — 上游数据坏了, 下游全静默错。

stm32f103-ref.json (653KB / 55 外设) 是 rm_lookup / gen_periph / gen_doc /
phase_minus_one 的共同上游: RCC 位写错一个 → 生成代码使能错外设
("外设死活不动"级 bug); IRQ 号错 → 中断静默不触发。此前 KB 无任何
一致性防线, 手改坏一个字段没人知道。本文件钉结构不变量 (黑盒校验):

  1. _meta.peripheral_count 与实际外设数一致 (漂移即红);
  2. base 地址落在 F103 外设地址空间 (含 GPIO 的多基地址特殊版式);
  3. relationships.clock: rcc_register ∈ 实测合法集 {APB1ENR, APB2ENR,
     AHBENR}, rcc_bit ∈ [0,32);
  4. relationships.pins: 端口 ∈ A~E, 引脚号 ∈ [0,15];
  5. relationships.irq: number ∈ [0,67] (F103 系外部 IRQ 上限), 名称符合
     CMSIS *_IRQn 命名;
  6. registers.offset 可按十六进制解析且 < 0x1000;
  7. f103_known_issues.json 非空 (已知硬件陷阱登记在册)。

校验规则取值依据: RM0008 (总线/寄存器)、Cortex-M3 TRM (IRQ 数)、
2026-09-08 全库实测 (clocks/bits/irq 的当前值域)。
"""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

from wb_common import TOOLKIT_ROOT  # noqa: E402

REF_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-ref.json")
ISSUES_PATH = os.path.join(TOOLKIT_ROOT, "data", "f103_known_issues.json")

_LEGAL_RCC_REGS = {"APB1ENR", "APB2ENR", "AHBENR"}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_hex(value) -> int:
    """KB 地址形态: 字符串 '0x...' / '0x...' (大小写混合)"""
    return int(str(value), 16)


class RefMetaConsistencyTests(unittest.TestCase):

    def setUp(self):
        self.ref = _load(REF_PATH)

    def test_peripheral_count_matches_meta(self):
        meta_count = self.ref["_meta"]["peripheral_count"]
        actual = len(self.ref["peripherals"])
        self.assertEqual(meta_count, actual,
                         "_meta.peripheral_count 与实际外设数漂移——"
                         "增删外设必须同步 _meta (文档单一事实源纪律)")
        self.assertGreaterEqual(actual, 50, "外设库缩水到不合理规模")

    def test_chip_identifier_is_f103c8(self):
        self.assertEqual(self.ref["_meta"]["chip"], "STM32F103C8T6")
        self.assertEqual(self.ref["_meta"]["flash_kb"], 64)
        self.assertEqual(self.ref["_meta"]["ram_kb"], 20)


class PeripheralBaseAddressTests(unittest.TestCase):

    def setUp(self):
        self.ref = _load(REF_PATH)
        self.peripherals = self.ref["peripherals"]

    def test_all_bases_in_peripheral_address_space(self):
        problems = []
        for name, pdata in self.peripherals.items():
            base = pdata.get("base")
            if not base:
                continue
            if " " in str(base):
                # GPIO 特殊版式: "A:0x40010800 B:0x40010C00 C:0x40011000"
                for part in str(base).split():
                    m = re.fullmatch(r"([A-E]):(0x[0-9A-Fa-f]+)", part)
                    if not m:
                        problems.append(f"{name}: 多基地址段 {part!r} 不合法")
                    elif not self._addr_legal(int(m.group(2), 16)):
                        problems.append(f"{name}: 地址 {part} 越界")
            else:
                addr = _parse_hex(base)
                if not self._addr_legal(addr):
                    problems.append(f"{name}: base {base} 越界")
        self.assertEqual(problems, [], "base 地址越界:\n" + "\n".join(problems))

    @staticmethod
    def _addr_legal(addr: int) -> bool:
        # 外设空间 (APB/AHB) / Cortex-M3 私有区 (NVIC/SysTick/SCB 本就在
        # 0xE0000000+) / FSMC 寄存器区 0xA0000000 (RM0008 外部存储控制器,
        # 高密度型号)
        return 0x40000000 <= addr < 0x60000000 or \
            0xE0000000 <= addr < 0xE0100000 or \
            0xA0000000 <= addr < 0xA0001000


class RelationshipInvariantsTests(unittest.TestCase):

    def setUp(self):
        self.ref = _load(REF_PATH)
        self.rel = self.ref["_relationships"]

    def test_clock_register_and_bit_in_legal_range(self):
        problems = []
        for name, rdata in self.rel.items():
            clock = rdata.get("clock") or {}
            if not clock:
                continue
            reg = clock.get("rcc_register")
            bit = clock.get("rcc_bit")
            if reg not in _LEGAL_RCC_REGS:
                problems.append(f"{name}: rcc_register={reg!r} 非法 "
                                f"(合法集 {sorted(_LEGAL_RCC_REGS)})")
            if not isinstance(bit, int) or not 0 <= bit < 32:
                problems.append(f"{name}: rcc_bit={bit!r} 越界")
            if not clock.get("rcc_bit_name"):
                problems.append(f"{name}: rcc_bit_name 缺失")
        self.assertEqual(problems, [], "clock 不变量破坏:\n" + "\n".join(problems))

    def test_pin_definitions_physically_valid(self):
        problems = []
        for name, rdata in self.rel.items():
            for pin_name, pinfo in (rdata.get("pins") or {}).items():
                port, num = pinfo.get("port"), pinfo.get("pin")
                if port not in "ABCDE" or len(str(port)) != 1:
                    problems.append(f"{name}.{pin_name}: 端口 {port!r} 非法")
                if not isinstance(num, int) or not 0 <= num <= 15:
                    problems.append(f"{name}.{pin_name}: 引脚号 {num!r} 越界")
                # mode 可选: 通道类/软件 CS 引脚 (TIM CH、ADC CH、SPI 各脚)
                # 实测不带 mode — 只在给了 mode 时校验非空
                if "mode" in pinfo and not pinfo["mode"]:
                    problems.append(f"{name}.{pin_name}: mode 为空字符串")
        self.assertEqual(problems, [], "引脚定义破坏:\n" + "\n".join(problems))

    def test_irq_numbers_and_cmsis_naming(self):
        problems = []
        for name, rdata in self.rel.items():
            irq = rdata.get("irq") or {}
            if not irq:
                continue
            num, irq_name = irq.get("number"), irq.get("name", "")
            if not isinstance(num, int) or not 0 <= num <= 67:
                problems.append(f"{name}: IRQ number={num!r} 越界 "
                                f"(F103 系外部 IRQ 上限 67)")
            if not str(irq_name).endswith("_IRQn"):
                problems.append(f"{name}: IRQ 名 {irq_name!r} 不符合 "
                                f"CMSIS *_IRQn 命名")
        self.assertEqual(problems, [], "IRQ 不变量破坏:\n" + "\n".join(problems))


class RegisterOffsetTests(unittest.TestCase):

    def test_offsets_parse_as_hex_and_stay_in_peripheral_block(self):
        ref = _load(REF_PATH)
        problems = []
        for pname, pdata in ref["peripherals"].items():
            for rname, rdata in (pdata.get("registers") or {}).items():
                off = rdata.get("offset")
                try:
                    value = _parse_hex(off)
                except (TypeError, ValueError):
                    problems.append(f"{pname}.{rname}: offset {off!r} 不可解析")
                    continue
                if not 0 <= value < 0x1000:
                    problems.append(f"{pname}.{rname}: offset {off} 越界")
        self.assertEqual(problems, [], "寄存器 offset 破坏:\n" + "\n".join(problems))


class KnownIssuesTests(unittest.TestCase):

    def test_known_issues_registry_is_populated(self):
        issues = _load(ISSUES_PATH)
        self.assertIsInstance(issues, dict)
        self.assertGreaterEqual(len(issues), 5,
                                "已知硬件陷阱登记簿近乎清空——"
                                "F103 errata 知识是生成器免责声明的依据")


if __name__ == "__main__":
    unittest.main()
