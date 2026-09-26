r"""gen_periph --timer 入参收口钉 (F-191, WB-20260926-02 T3 — 销 WB-05 M-2 老账)。

病灶: --timer 无收口, gen_timer_int / gen_pwm 内三连 .get 缺省
(TIM_BUS.get(timer,"APB1") / TIM_CLOCK_BIT.get(timer,f"{timer}EN") /
tim_irq.get(timer,28)) 会把任何未登记名生成"看起来合法"的错码 —
WB-20260925-01 M-2 实录: --timer TIM9 产出 RCC_APB1ENR_TIM9EN (CMSIS
不存在) / ISER 28 (TIM2 的) / 内核时钟误走 pclk1 分支。

收口口径 (F-185 P-3 --baud-div 同法: CLI 层显式校验 → _emit
"/* ERROR" → exit 1, 合法集随文案): 登记集 = gen-maps tim_bus ∪ tim_irq
键集 (= ref.json _relationships 收编的 TIM 全集, 11 个)。不取 ref.json
TIM 字面全集 (14 个): TIM8/10/11 无 _relationships 条目, tim_irq 无源
可互证 — 放行即生成半伪代码, 违 F-103 fail-fast。

TIM9 三处全对钉 (01 报告 §一 M-2 复现命令当验收命令):
  ① RCC->APB2ENR |= RCC_APB2ENR_TIM9EN;   (修前: APB1ENR 宏不存在)
  ② NVIC->ISER[0] = (1UL << 24);          (修前: 28 是 TIM2 的)
  ③ 时钟路径: --pclk1 18 下 TIM_CLK 恒 72MHz (修前: 误走 pclk1 分支得 36)
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402


def _run_cli(argv):
    """进程内驱动 main(): patch argv + 捕获 stdout, 返回 (退出码, 输出)。

    SystemExit 语义与 test_json_exit_code_contract 同口径: None=0,
    int 原样, 其余按失败计 1。"""
    buf = io.StringIO()
    code = 0
    with mock.patch.object(sys, "argv", ["gen_periph.py"] + argv), \
            contextlib.redirect_stdout(buf):
        try:
            gen_periph.main()
        except SystemExit as exc:
            if exc.code is None:
                code = 0
            elif isinstance(exc.code, int):
                code = exc.code
            else:
                code = 1
    return code, buf.getvalue()


class Tim9GenerationPins(unittest.TestCase):
    """验收钉: 01 报告 M-2 复现命令修后三处全对 (APB2ENR/ISER 位号/时钟路径)。"""

    def test_tim9_default_clocks_three_places(self):
        code, out = _run_cli(
            ["--type", "timer-int", "--timer", "TIM9", "--period-ms", "10"])
        self.assertEqual(code, 0, out)
        # ① 总线/使能宏: TIM9 属 APB2 (APB2ENR[19]=TIM9EN, ref.json 双源)
        self.assertIn("RCC->APB2ENR |= RCC_APB2ENR_TIM9EN;", out)
        self.assertNotIn("APB1ENR_TIM9EN", out)
        # ② ISER 位号: TIM1_BRK_TIM9 = 24 (28 是 TIM2 的)
        self.assertIn("NVIC->ISER[0] = (1UL << 24);", out)
        self.assertNotIn("(1UL << 28)", out)
        # ③ 时钟路径: 默认 hclk=72 → TIM_CLK=72MHz, PSC 注释 1MHz tick
        self.assertIn("TIM_CLK=72MHz", out)
        self.assertIn("// 72MHz/(71+1) = 1000000Hz", out)

    def test_tim9_kernel_clock_immune_to_pclk1(self):
        """③ 路径判别钉: APB2 定时器不走 pclk1 派生分支。

        修前 tim_bus 缺键 → APB1 缺省 → tim_kernel_clock_mhz(72,18)=36 →
        TIM_CLK=36MHz, 非缺省 --pclk1 组合下 tick 算错 (M-2 错③)。
        修后 APB2 路径与 pclk1 无关。"""
        code, out = _run_cli(
            ["--type", "timer-int", "--timer", "TIM9", "--period-ms", "10",
             "--pclk1", "18"])
        self.assertEqual(code, 0, out)
        self.assertIn("TIM_CLK=72MHz", out)
        self.assertNotIn("TIM_CLK=36MHz", out)


class TimerEntryGateTests(unittest.TestCase):
    """未登记名 → ERROR exit 1, 文案给合法集 (F-185 P-3 同款契约)。"""

    def test_timer_int_unregistered_name_fails_fast(self):
        code, out = _run_cli(
            ["--type", "timer-int", "--timer", "TIM99", "--period-ms", "10"])
        self.assertEqual(code, 1, "未登记 --timer 须 exit 1 (F-103 禁静默回落)")
        self.assertTrue(out.startswith("/* ERROR"), out)
        self.assertIn("TIM99", out)
        self.assertIn("TIM9", out)  # 合法集必须随文案出现

    def test_pwm_unregistered_name_fails_fast(self):
        code, out = _run_cli(
            ["--type", "pwm", "--timer", "TIM99", "--ch", "1", "--pin", "PA0",
             "--freq", "1000"])
        self.assertEqual(code, 1, "pwm 路同受一处闸管辖")
        self.assertTrue(out.startswith("/* ERROR"), out)

    def test_registered_timers_still_generate(self):
        """金样钉: 已登记名走原路不受闸影响 (TIM2 生成物不变)。"""
        code, out = _run_cli(
            ["--type", "timer-int", "--timer", "TIM2", "--period-ms", "1"])
        self.assertEqual(code, 0, out)
        self.assertIn("RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;", out)
        self.assertIn("NVIC->ISER[0] = (1UL << 28);", out)


if __name__ == "__main__":
    unittest.main()
