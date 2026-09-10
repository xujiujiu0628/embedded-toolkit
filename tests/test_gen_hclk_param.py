r"""F-110: gen_periph --hclk 时钟树参数化回归钉。

spec: embedded-handoff/docs/superpowers/specs/2026-09-11-f110-hclk-param-design.md

覆盖:
  ① 默认兼容钉——--hclk 缺省 (=72) 时代表性 snippet 逐字节 == 基线
     (既有四测试文件零修改全绿是第一层证明, 本文件钉显式声明该契约);
  ② 推导函数本身 (apb_clock_mhz: APB2=hclk, APB1=hclk//2 floor);
  ③ hclk=8 (HSI 直跑, 最现实第二配置) 各生成器实样钉;
  ④ 优先级契约: 显式 --tim-clk > hclk 推导;
  ⑤ 边界钉: hclk 域 [2,72] 越界 ERROR→exit 1 (F-103 纪律, _emit);
  ⑥ 奇数 hclk floor 注释如实。
"""
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts", "gen_periph.py")


def _run_cli(argv):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, SCRIPT] + argv, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, env=env)


class ApbClockDerivationTests(unittest.TestCase):
    def test_standard_prescalers(self):
        # 标准分频 (HPRE=1/PPRE2=1/PPRE1=2): APB2=hclk, APB1=hclk//2
        self.assertEqual(gen_periph.apb_clock_mhz(72, "APB2"), 72)
        self.assertEqual(gen_periph.apb_clock_mhz(72, "APB1"), 36)
        self.assertEqual(gen_periph.apb_clock_mhz(8, "APB2"), 8)
        self.assertEqual(gen_periph.apb_clock_mhz(8, "APB1"), 4)

    def test_odd_hclk_floors(self):
        # floor 不四舍五入: 9//2=4 (非 5)
        self.assertEqual(gen_periph.apb_clock_mhz(9, "APB1"), 4)


class DefaultCompatTests(unittest.TestCase):
    """① 核心兼容契约: 不传 hclk (或显式 72) 输出逐字节一致"""

    def test_explicit_72_equals_default_everywhere(self):
        pairs = [
            (lambda: gen_periph.gen_usart("USART1", 115200, "PA9", "PA10"),
             lambda h: gen_periph.gen_usart("USART1", 115200, "PA9", "PA10", h)),
            (lambda: gen_periph.gen_systick(1000),
             lambda h: gen_periph.gen_systick(1000, h)),
            (lambda: gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50),
             lambda h: gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50, None, h)),
            (lambda: gen_periph.gen_timer_int("TIM2", 1, 72),
             lambda h: gen_periph.gen_timer_int("TIM2", 1, None, h)),
            (lambda: gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7"),
             lambda h: gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7", h)),
            (lambda: gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6", "PA7", 16),
             lambda h: gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6", "PA7", 16, h)),
            (lambda: gen_periph.gen_adc("ADC1", 1, "PA1"),
             lambda h: gen_periph.gen_adc("ADC1", 1, "PA1", h)),
        ]
        for baseline_fn, param_fn in pairs:
            with self.subTest(fn=baseline_fn):
                self.assertEqual(baseline_fn(), param_fn(72),
                                 "hclk=72 显式传值必须与缺省逐字节一致")

    def test_timer_int_default_derivation_equals_72(self):
        # gen_timer_int 缺省 (tim_clk=None→hclk=72) 与旧显式 72 逐字节一致
        self.assertEqual(gen_periph.gen_timer_int("TIM2", 1, 72),
                         gen_periph.gen_timer_int("TIM2", 1))


class Hclk8RealSamplesTests(unittest.TestCase):
    """③ hclk=8 (HSI 直跑) 实样钉——手算值"""

    def test_usart_brr_at_8mhz(self):
        # USART1@115200, pclk2=8MHz: div = 8e6/(16*115200) = 4.3403
        # mantissa=4, frac=round(0.3403*16)=5 → BRR=0x45
        out = gen_periph.gen_usart("USART1", 115200, "PA9", "PA10", 8)
        self.assertIn("USART1->BRR = 0x0045;", out)
        self.assertIn("PCLK2=8MHz", out)
        # USART2 (APB1=4MHz): div = 4e6/(16*115200)=2.1701 → m=2 f=round(2.72)=3
        out2 = gen_periph.gen_usart("USART2", 115200, "PA2", "PA3", 8)
        self.assertIn("USART2->BRR = 0x0023;", out2)

    def test_systick_load_at_8mhz(self):
        out = gen_periph.gen_systick(1000, 8)
        self.assertIn("SysTick->LOAD = 7999;", out)
        self.assertIn("8MHz core clock", out)

    def test_i2c_cr2_freq_at_8mhz(self):
        # CR2 FREQ = PCLK1 MHz = 4 (旧版恒 36)
        out = gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7", 8)
        self.assertIn("I2C1->CR2 = 4; ", out + " ")

    def test_adc_prescaler_auto_downshifts(self):
        # hclk=8 → pclk2=8, /2=4MHz ≤14 → 最小合规分频 =/2 (bits=00)
        out = gen_periph.gen_adc("ADC1", 1, "PA1", 8)
        self.assertIn("ADCPRE=/2 (4MHz @ PCLK2=8MHz", out)
        self.assertIn("RCC->CFGR |=  (0UL << 14);", out)
        # hclk=72 仍 /6 (兼容, 也覆盖"自动选择"不改变默认行为)
        self.assertIn("ADCPRE=/6 (12MHz @ PCLK2=72MHz",
                      gen_periph.gen_adc("ADC1", 1, "PA1", 72))
        # hclk=56: /2=28 ✗ /4=14 ✓ → /4
        self.assertIn("ADCPRE=/4 (14MHz @ PCLK2=56MHz",
                      gen_periph.gen_adc("ADC1", 1, "PA1", 56))

    def test_timer_int_ticks_at_8mhz(self):
        # gen_timer_int: PSC 固定 71, ARR = tim_clk*1e6//((PSC+1)*target_hz)-1
        # = 8e6//(72*1000)-1 = 110 (72MHz 下该式 = 999——结构随 hclk 缩放)
        out = gen_periph.gen_timer_int("TIM2", 1, None, 8)
        self.assertIn("->PSC = 71;", out)
        self.assertIn("->ARR = 110;", out)
        self.assertIn("8MHz", out)
        # ARR 16 位溢出阈值随 hclk 下移: 72MHz 下 63ms 才溢出, 8MHz 下
        # 同一 target_hz=15 已需 ARR = 8e6//1080-1 ≈ 7406 (仍合法) →
        # 长周期在低频下反而可表示 (无溢出) — 行为随参数连续, 钉一例
        self.assertIn("->ARR =", gen_periph.gen_timer_int("TIM2", 63, None, 8))


class TimClkPriorityTests(unittest.TestCase):
    """④ 优先级契约: 显式 tim_clk > hclk 推导"""

    def test_explicit_tim_clk_wins(self):
        out = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50, 72, 8)
        self.assertIn("TIM_CLK=72MHz", out)
        out_none = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50, None, 8)
        self.assertIn("TIM_CLK=8MHz", out_none)
        # timer-int 同理
        self.assertIn("TIM_CLK=72MHz",
                      gen_periph.gen_timer_int("TIM2", 1, 72, 8))
        self.assertIn("TIM_CLK=8MHz",
                      gen_periph.gen_timer_int("TIM2", 1, None, 8))


class HclkDomainTests(unittest.TestCase):
    """⑤ 边界: hclk ∈ [2,72], 越界 ERROR→exit 1"""

    def test_out_of_range_errors(self):
        for bad in (0, 1, -5, 73, 999):
            with self.subTest(hclk=bad):
                r = _run_cli(["--type", "systick", "--freq", "1000",
                              "--hclk", str(bad)])
                self.assertEqual(r.returncode, 1,
                                 f"hclk={bad} 应拒绝:\n{r.stdout[:200]}")
                self.assertIn("ERROR", r.stdout)
                self.assertIn("--hclk", r.stdout)

    def test_in_range_ok(self):
        for good in (2, 8, 72):
            with self.subTest(hclk=good):
                r = _run_cli(["--type", "systick", "--freq", "1000",
                              "--hclk", str(good)])
                self.assertEqual(r.returncode, 0, r.stdout[:200])

    def test_gpio_type_skips_hclk_check(self):
        # gpio/doc 不涉时钟: hclk 越界也不该拦 (参数无关性)
        r = _run_cli(["--type", "gpio", "--pin", "PA0", "--hclk", "999"])
        self.assertEqual(r.returncode, 0, r.stdout[:200])


class OddHclkHonestAnnotationTests(unittest.TestCase):
    """⑥ 奇数 hclk: floor 结果必须如实出现在注释里 (不假装精确)"""

    def test_usart2_pclk_annotation(self):
        out = gen_periph.gen_usart("USART2", 9600, "PA2", "PA3", 9)
        # 9//2=4 (floor) → 注释与计算都用 4
        self.assertIn("PCLK1=4MHz", out)
        self.assertNotIn("PCLK1=4.5", out)


if __name__ == "__main__":
    unittest.main()
