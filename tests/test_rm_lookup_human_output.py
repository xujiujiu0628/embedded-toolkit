r"""rm_lookup 人读输出键面钉 (F-191, WB-20260926-02 T4 — 收 WB-20260925-01 L-1)。

病灶 (L-1 双脱靶): format_result 三处读 `description` 而数据面键是
`desc` (55 外设 desc=55 / description=0, 寄存器级 desc=711 /
description=0) → 人读"描述恒空" (WB-05 M-3 旧账); `clock_enable` 死键
(0/55) → "时钟使能"行 55/55 永不出场。JSON 模式不受影响。

修法: description→desc 三处 (format_result 外设/寄存器 + --list);
clock_enable 死支改从 ref_data["_relationships"] 反查 (clock 真 →
APB1ENR[0] TIM2EN 形态; EXTI 的 clock=null+clock_note 显式豁免形态 →
呈现 note 文案, F-186 纪律禁静默缺席)。

期望值全部从 ref.json 自身反查 (F-186 反查纪律), 断言钉人读输出含
数据面原文 — 修前必红。
"""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import rm_lookup  # noqa: E402
from wb_common import TOOLKIT_ROOT  # noqa: E402

REF_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-ref.json")


def _load_ref():
    with open(REF_PATH, encoding="utf-8") as f:
        return json.load(f)


def _run_cli(argv):
    """进程内驱动 main(): patch argv + 捕获 stdout。"""
    buf = io.StringIO()
    with mock.patch.object(sys, "argv", ["rm_lookup.py"] + argv), \
            contextlib.redirect_stdout(buf):
        rm_lookup.main()
    return buf.getvalue()


class HumanReadableDescPins(unittest.TestCase):
    """人读路径必须呈现数据面 desc 原文 (三处 description 死键收口钉)。"""

    def setUp(self):
        self.ref = _load_ref()

    def test_peripheral_query_shows_desc(self):
        want = self.ref["peripherals"]["RCC"]["desc"]
        self.assertTrue(want, "RCC.desc 自身为空 — 钉前提失效")
        out = _run_cli(["RCC"])
        self.assertIn(f"RCC — {want}", out)

    def test_register_query_shows_desc(self):
        want = self.ref["peripherals"]["RCC"]["registers"]["APB2ENR"]["desc"]
        out = _run_cli(["APB2ENR"])
        self.assertIn(want, out)

    def test_list_shows_desc(self):
        want = self.ref["peripherals"]["TIM2"]["desc"]
        out = _run_cli(["--list"])
        self.assertIn(f"[TIM2] {want}", out)


class ClockEnableReverseLookupPins(unittest.TestCase):
    """clock_enable 死支改反查 — 22 条 rel 全带 clock, EXTI=null+note 呈 note。"""

    def setUp(self):
        self.ref = _load_ref()

    def test_tim2_shows_reverse_lookup_clock_line(self):
        clk = self.ref["_relationships"]["TIM2"]["clock"]
        want = (f"时钟使能: {clk['rcc_register']}[{clk['rcc_bit']}] "
                f"{clk['rcc_bit_name']}")
        out = _run_cli(["TIM2"])
        self.assertIn(want, out)

    def test_exti_null_clock_presents_note(self):
        self.assertIsNone(self.ref["_relationships"]["EXTI"]["clock"],
                          "EXTI 应为 clock=null 显式豁免形态 (F-186 快照)")
        note = self.ref["_relationships"]["EXTI"]["clock_note"]
        self.assertTrue(note, "EXTI.clock_note 自身为空 — 钉前提失效")
        out = _run_cli(["EXTI"])
        self.assertIn(note, out)


class JsonModeRegressionPins(unittest.TestCase):
    """JSON 模式零变化 (回归钉): 键集与数据面内容不受人读修影响。"""

    def setUp(self):
        self.ref = _load_ref()

    def test_json_query_structure_and_data_unchanged(self):
        out = _run_cli(["--json", "RCC"])
        result = json.loads(out)
        self.assertEqual(
            set(result),
            {"query", "peripherals", "registers", "bits", "recipes"})
        self.assertEqual(result["query"], "RCC")
        self.assertEqual(result["peripherals"][0]["name"], "RCC")
        want = self.ref["peripherals"]["RCC"]["desc"]
        self.assertEqual(result["peripherals"][0]["data"]["desc"], want)


if __name__ == "__main__":
    unittest.main()
