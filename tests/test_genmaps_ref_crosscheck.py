r"""gen-maps ↔ ref.json 类级互证 (F-191, WB-20260926-02 T2 — 收 WB-20260925-01 M-2)。

病灶 (M-2 实录): data/stm32f103-gen-maps.json 是与 ref.json 平行的第二套
bus/IRQ 事实源, F-179 修正 ref.json 时未随动 — tim_bus 只有 TIM1=APB2、
tim_irq 只有 TIM1~4, `--timer TIM9` 生成三层错代码 (APB1ENR_TIM9EN 宏在
CMSIS 不存在 / ISER 28 是 TIM2 的 / 内核时钟误走 pclk1 分支)。

本钉同 F-179 类级防线范式 (test_ref_bus_crosscheck.py): 推导期望的全部
输入来自 ref.json 与 gen-maps 两文件自身, 不引外部记忆 —

  * tim_bus 逐键三源互证: peripherals.<P>.bus、_relationships.<P>.bus、
    clock.rcc_register 的总线前缀;
  * tim_irq 逐键: _relationships.<P>.irq.number + peripherals.<P>.interrupts
    第三源;
  * 类级补齐 (防类不防点): _relationships 里每个 TIM 外设必须在两域都有键
    —— 下一笔同类缺键 (如未来 rel 收编 TIM8/10/11) 必被咬;
  * tim_clock_bit / tim_ch_pins 本单不改值, 只进互证面: 前者证位名在 RCC
    位表存在 (只证在位不证值 — 位号无独立第二源, 缺源列 P 面), 后者对
    _relationships.<P>.pins.CHn 互证。

豁免形态沿用 F-186 "显式 null+note" 纪律: 现状 11 条 TIM 全部可互证、无
豁免; 未来加键若确实无互证源, 须在 gen-maps 带显式 note 并在本文件登记
快照, 禁静默缺席。
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
MAPS_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-gen-maps.json")

# 使能寄存器 → 所属总线 (与 test_ref_bus_crosscheck._ENR_TO_BUS 同源口径)
_ENR_TO_BUS = {"APB1ENR": "APB1", "APB2ENR": "APB2", "AHBENR": "AHB"}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _tim_rels(ref):
    """_relationships 里 TIM 家族条目 (键形 TIMx, x 纯数字)。"""
    return {k: v for k, v in (ref.get("_relationships") or {}).items()
            if re.fullmatch(r"TIM\d+", k)}


class TimBusCrosscheckTests(unittest.TestCase):
    """tim_bus 逐键三源互证 + 类级补齐 (M-2 缺键家族主钉)。"""

    def setUp(self):
        self.ref = _load(REF_PATH)
        self.maps = _load(MAPS_PATH)
        self.rels = _tim_rels(self.ref)

    def test_every_tim_bus_key_agrees_with_ref(self):
        problems = []
        for key in sorted(self.maps["tim_bus"]):
            bus = self.maps["tim_bus"][key]
            per = self.ref["peripherals"].get(key)
            if per is None:
                problems.append(f"tim_bus.{key}: 外设键不在 ref.json — 键面越界")
                continue
            if key not in self.rels:
                problems.append(
                    f"tim_bus.{key}: 不在 _relationships — 无互证源 "
                    "(加键须先有 ref.json 关系条目, 或走显式豁免快照)")
                continue
            rel = self.rels[key]
            if per.get("bus") != bus:
                problems.append(
                    "tim_bus.{0}={1!r} 但 peripherals.{0}.bus={2!r}".format(
                        key, bus, per.get("bus")))
            rel_bus = rel.get("bus")
            if rel_bus is not None and rel_bus != bus:
                problems.append(
                    "tim_bus.{0}={1!r} 但 _relationships.{0}.bus={2!r}".format(
                        key, bus, rel_bus))
            clock = rel.get("clock") or {}
            reg = clock.get("rcc_register")
            if reg is not None:
                reg_bus = _ENR_TO_BUS.get(reg)
                if reg_bus is None:
                    problems.append(
                        "tim_bus.{0}: clock.rcc_register={1!r} 不在互证寄存"
                        "器集 {2}".format(key, reg, sorted(_ENR_TO_BUS)))
                elif reg_bus != bus:
                    problems.append(
                        "tim_bus.{0}={1!r} 但 {2}[{3}]={4} 属 {5}".format(
                            key, bus, reg, clock.get("rcc_bit"),
                            clock.get("rcc_bit_name"), reg_bus))
        self.assertEqual(
            problems, [],
            "tim_bus 与 ref.json 矛盾 (M-2 家族):\n" + "\n".join(problems))

    def test_tim_bus_covers_every_relationships_tim(self):
        missing = sorted(set(self.rels) - set(self.maps["tim_bus"]))
        self.assertEqual(
            missing, [],
            "_relationships TIM 外设缺 tim_bus 键 (M-2 缺键家族 — "
            "gen_periph 将按 APB1 缺省生成错码): %r" % (missing,))


class TimIrqCrosscheckTests(unittest.TestCase):
    """tim_irq 逐键互证 (rel.irq + per.interrupts 双源) + 类级补齐。"""

    def setUp(self):
        self.ref = _load(REF_PATH)
        self.maps = _load(MAPS_PATH)
        self.rels = _tim_rels(self.ref)

    def test_every_tim_irq_key_matches_relationships_irq(self):
        problems = []
        for key in sorted(self.maps["tim_irq"]):
            num = self.maps["tim_irq"][key]
            rel = self.rels.get(key)
            if rel is None:
                problems.append(
                    f"tim_irq.{key}={num}: 不在 _relationships — 无互证源")
                continue
            rel_num = (rel.get("irq") or {}).get("number")
            if rel_num != num:
                problems.append(
                    "tim_irq.{0}={1} 但 _relationships.{0}.irq.number="
                    "{2!r}".format(key, num, rel_num))
            ints = self.ref["peripherals"].get(key, {}).get("interrupts") or []
            int_nums = {i.get("value") for i in ints if isinstance(i, dict)}
            if int_nums and num not in int_nums:
                problems.append(
                    "tim_irq.{0}={1} 不在 peripherals.{0}.interrupts 值集 "
                    "{2}".format(key, num, sorted(x for x in int_nums
                                                  if x is not None)))
        self.assertEqual(
            problems, [],
            "tim_irq 与 ref.json 矛盾 (M-2 家族):\n" + "\n".join(problems))

    def test_tim_irq_covers_every_relationships_tim(self):
        missing = sorted(set(self.rels) - set(self.maps["tim_irq"]))
        self.assertEqual(
            missing, [],
            "_relationships TIM 外设缺 tim_irq 键 (M-2 缺键家族 — "
            "gen_periph 将按 28 (TIM2) 缺省生成错码): %r" % (missing,))


class TimClockBitCrosscheckTests(unittest.TestCase):
    """tim_clock_bit 位名存在性互证 (本单不改值; 只证在位不证值)。

    TIMxEN 的位号只登记在 RCC 位表一处, 无独立第二源可反查 — "在位"
    即全部可证面; 位号语义若错置由消费面错码复现走 P 面, 不在本钉
    冒充已证。
    """

    def setUp(self):
        self.ref = _load(REF_PATH)
        self.maps = _load(MAPS_PATH)

    def test_every_tim_clock_bit_name_exists_in_rcc_table(self):
        problems = []
        rcc_regs = self.ref["peripherals"]["RCC"]["registers"]
        for key in sorted(self.maps["tim_clock_bit"]):
            bit_name = self.maps["tim_clock_bit"][key]
            bus = self.maps["tim_bus"].get(key)
            if bus is None:
                problems.append(
                    f"tim_clock_bit.{key}: tim_bus 无该键, 无法定位使能寄存器")
                continue
            bits = (rcc_regs.get(f"{bus}ENR") or {}).get("bits") or {}
            names = {info.get("name") for info in bits.values()
                     if isinstance(info, dict)}
            if bit_name not in names:
                problems.append(
                    "tim_clock_bit.{0}={1!r} 不在 RCC {2}ENR 位名集 {3}".format(
                        key, bit_name, bus,
                        sorted(n for n in names if n)))
        self.assertEqual(
            problems, [],
            "tim_clock_bit 位名在 RCC 位表不存在:\n" + "\n".join(problems))


class TimChPinsCrosscheckTests(unittest.TestCase):
    """tim_ch_pins 对 _relationships.pins.CHn 互证 (本单不改值)。"""

    def setUp(self):
        self.ref = _load(REF_PATH)
        self.maps = _load(MAPS_PATH)
        self.rels = _tim_rels(self.ref)

    def test_every_tim_ch_pin_matches_relationships_pins(self):
        problems = []
        for key in sorted(self.maps["tim_ch_pins"]):
            timer, ch = key.split(":")
            pin = self.maps["tim_ch_pins"][key]
            rel = self.rels.get(timer)
            if rel is None:
                problems.append(
                    f"tim_ch_pins.{key}: {timer} 不在 _relationships")
                continue
            ch_info = (rel.get("pins") or {}).get(f"CH{ch}")
            if ch_info is None:
                problems.append(
                    "tim_ch_pins.{0}={1!r} 但 _relationships.{2}.pins 无 "
                    "CH{3}".format(key, pin, timer, ch))
                continue
            want = f"P{ch_info.get('port')}{ch_info.get('pin')}"
            if want != pin:
                problems.append(
                    "tim_ch_pins.{0}={1!r} 但 _relationships.{2}.pins.CH{3}="
                    "{4!r}".format(key, pin, timer, ch, want))
        self.assertEqual(
            problems, [],
            "tim_ch_pins 与 _relationships.pins 矛盾:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
