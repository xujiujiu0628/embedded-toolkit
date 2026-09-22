r"""ref.json 总线归属「类级」防线 (WB-20260920-05 / F-179, GAP-D-5)。

点位修正只保证"这一个对"；本钉从 ref.json **自身**的 RCC 时钟使能位名反推
「外设→总线」期望集，逐外设比对 `peripherals.<P>.bus` —— 下一个同类录入
矛盾必须被咬（防类不防点，简报 §2 T1）。

推导规则（全部输入来自 ref.json 自身，不引外部记忆）：
  * `RCC.APB1ENR` / `APB2ENR` / `AHBENR` 各位的 `name` 去尾部 "EN" 得候选键；
  * 候选键命中 `peripherals` 时，该外设 bus 必须等于该寄存器对应的总线；
  * GPIO 特例：`IOPAEN`..`IOPGEN` → `GPIOA`..`GPIOG`；
  * 无对应外设条目的位名（SRAMEN / FLITFEN）自然跳过。

GAP-D-5 事实（修前）：peripherals.TIM9.bus=APB1 而 APB2ENR bit19=TIM9EN；
peripherals.TIM12/13/14.bus=APB2 而 APB1ENR bits 6/7/8=TIM12/13/14EN。
本钉由 ref.json 单文件自证，故该矛盾在被修正前必红（数据 bug 的第三源实证，
前两源=工厂状态文档 GAP-D-5 取证 + 样例侧 f103-tim9-14 注释）。
"""
import json
import re
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

from wb_common import TOOLKIT_ROOT  # noqa: E402

REF_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-ref.json")

# 时钟使能寄存器 → 该寄存器位所使能的外设所属总线
_ENR_TO_BUS = {"APB1ENR": "APB1", "APB2ENR": "APB2", "AHBENR": "AHB"}


def _load_ref():
    with open(REF_PATH, encoding="utf-8") as f:
        return json.load(f)


def _candidate_keys(bit_name):
    """时钟使能位名 → 候选外设键列表（含 IOPx→GPIOx 规则）。"""
    if not str(bit_name).endswith("EN"):
        return []
    stem = str(bit_name)[:-2]
    keys = [stem]
    if len(stem) == 4 and stem.startswith("IOP"):
        keys.append("GPIO" + stem[3])
    return keys


def derive_expected_bus(ref):
    """返回 (期望集, 自相矛盾集)。

    期望集: {外设键: {"bus":.., "src": "APB2ENR[19]=TIM9EN"}}
    自相矛盾集: 同一外设键被两个不同总线的 ENR 位命中 (推导规则本身先自检)
    """
    periphs = ref["peripherals"]
    enr_regs = periphs["RCC"]["registers"]
    expected = {}
    conflicts = []
    for reg, bus in sorted(_ENR_TO_BUS.items()):
        bits = (enr_regs.get(reg) or {}).get("bits") or {}
        for bit, info in sorted(bits.items(), key=lambda kv: int(kv[0])):
            name = info.get("name", "")
            for key in _candidate_keys(name):
                if key not in periphs:
                    continue
                src = "{0}[{1}]={2}".format(reg, bit, name)
                if key in expected and expected[key]["bus"] != bus:
                    conflicts.append(
                        "{0}: {1} vs {2} ({3})".format(
                            key, expected[key]["src"], src,
                            expected[key]["bus"] + "/" + bus))
                    continue
                expected.setdefault(key, {"bus": bus, "src": src})
    return expected, conflicts


class BusCrosscheckDerivationTests(unittest.TestCase):
    """推导规则自身的健全性：期望集不能缩水成空壳，否则防线形同虚设。"""

    def setUp(self):
        self.ref = _load_ref()

    def test_derivation_is_non_trivial_and_self_consistent(self):
        expected, conflicts = derive_expected_bus(self.ref)
        self.assertEqual(conflicts, [],
                         "RCC 使能位名自相矛盾（同一外设落在两条总线）:\n"
                         + "\n".join(conflicts))
        # 修前实测 46 个外设由 ENR 位名覆盖；低于 40 说明推导规则被改坏
        self.assertGreaterEqual(
            len(expected), 40,
            "由 RCC 使能位名推得的外设数骤减——推导规则或数据被改坏")


class PeripheralBusFieldTests(unittest.TestCase):
    """类级断言：每个可由 ENR 位名定位的外设，bus 字段必须一致。"""

    def test_every_peripheral_bus_matches_rcc_bit_owner(self):
        ref = _load_ref()
        expected, _ = derive_expected_bus(ref)
        periphs = ref["peripherals"]
        problems = []
        for name in sorted(expected):
            want = expected[name]
            actual = periphs[name].get("bus")
            if actual != want["bus"]:
                problems.append(
                    "peripherals.{0}.bus={1!r} 但 {2} 属 {3}".format(
                        name, actual, want["src"], want["bus"]))
        self.assertEqual(
            problems, [],
            "外设 bus 字段与 RCC 使能位归属矛盾（GAP-D-5 家族）:\n"
            + "\n".join(problems))


def _is_shared_vector_name(irq_name):
    """共享向量名（如 TIM1_BRK_TIM9_IRQn）在 CMSIS 里是**一个**枚举，
    名下挂多个定时器；判定为中断记号 ≥2 个（下划线分段 ≥3）。"""
    name = str(irq_name)
    stem = name[:-len("_IRQn")] if name.endswith("_IRQn") else name
    return len(stem.split("_")) >= 3


class IrqNumberUniquenessTests(unittest.TestCase):
    """顺带钉：`_relationships` 内 IRQ 号在**非共享名**场景不得重复。

    GAP-D-3 增补（T2）后本钉仍须绿；共享向量名（TIM1_BRK_TIM9 系）如实
    按 CMSIS 枚举登记、不拆假名，故同名多外设共用一号不算矛盾。
    """

    def test_irq_numbers_unique_outside_shared_vector_names(self):
        ref = _load_ref()
        rels = ref.get("_relationships") or {}
        by_number = {}
        for periph, rdata in rels.items():
            irq = rdata.get("irq") or {}
            if not irq:
                continue
            by_number.setdefault(irq.get("number"), []).append(
                (periph, irq.get("name", "")))
        problems = []
        for number in sorted(by_number):
            entries = by_number[number]
            distinct = set(n for _, n in entries)
            if len(distinct) < 2:
                continue
            for periph, irq_name in entries:
                if not _is_shared_vector_name(irq_name):
                    problems.append(
                        "IRQ {0}: {1}({2}) 与其它条目共用中断号".format(
                            number, periph, irq_name))
        self.assertEqual(problems, [], "IRQ 号重复:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()


class CoreBlockPeripheralsTests(unittest.TestCase):
    """F-185 (GAP-D-6 裁决): 核心块外设的 bus 口径 = "core", 且全表 bus 封闭。"""

    CORE_BASE_RE = (0xE0000000, 0xE0100000)
    # 现场快照 (2026-09-22, F-179 后): 基址落核心块区间的外设
    CORE_SNAPSHOT = {"NVIC", "SysTick", "DBG"}

    def test_all_peripheral_bus_values_are_closed_set(self):
        ref = _load_ref()
        bad = {k: v.get("bus") for k, v in ref["peripherals"].items()
               if v.get("bus") not in ("APB1", "APB2", "AHB", "core")}
        self.assertEqual(bad, {}, "存在 bus 取值越界的外设 (F-103 口径禁止敷衍值): %r" % bad)

    def test_core_block_peripherals_declare_core_bus(self):
        ref = _load_ref()
        lo, hi = self.CORE_BASE_RE
        core = set()
        for k, v in ref["peripherals"].items():
            base = v.get("base")
            # 仅纯十六进制形态参与判定; 多实例串 (如 GPIO "A:0x.. B:0x..") 非核心块
            if isinstance(base, str) and re.fullmatch(r"0x[0-9A-Fa-f]+", base):
                if lo <= int(base, 16) < hi:
                    core.add(k)
        self.assertEqual(core, self.CORE_SNAPSHOT,
                         "核心块外设集合变化须过设计 (更新快照须附出处)")
        for k in core:
            self.assertEqual(ref["peripherals"][k].get("bus"), "core", k)
