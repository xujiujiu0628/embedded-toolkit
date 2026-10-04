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


class AdcExactBoundTests(unittest.TestCase):
    """F-111 (复审 H-1): ADCPRE 选档精确比较——floor 不得粉饰越限"""

    def test_floor_masquerade_points_now_exact(self):
        # 复审实测越限四点, 修复前 floor 判 /2 "合规"; 精确比较下
        # 自动落到首个真合规档 (57<=14*6=84 → /6, 非 /8——9.5MHz<14)
        out = gen_periph.gen_adc("ADC1", 1, "PA1", 29)
        self.assertIn("ADCPRE=/4", out)        # 29/2=14.5 ✗ → 29<=56 /4 ✓
        self.assertIn("7.25MHz @ PCLK2=29MHz", out)
        for h, div_s, shown in ((57, "/6", "9.50MHz"),
                                (58, "/6", "9.67MHz"),
                                (59, "/6", "9.83MHz")):
            with self.subTest(hclk=h):
                out = gen_periph.gen_adc("ADC1", 1, "PA1", h)
                self.assertIn(f"ADCPRE={div_s}", out)
                self.assertIn(shown, out)

    def test_exact_divisible_unchanged(self):
        # 整除场景输出保持纯整数形态 (兼容契约延伸): 72→/6 12MHz, 8→/2 4MHz
        self.assertIn("ADCPRE=/6 (12MHz @ PCLK2=72MHz",
                      gen_periph.gen_adc("ADC1", 1, "PA1", 72))
        self.assertIn("ADCPRE=/2 (4MHz @ PCLK2=8MHz",
                      gen_periph.gen_adc("ADC1", 1, "PA1", 8))
        # pclk2=28 边界: /2=14 恰合规 (精确比较下仍 /2)
        self.assertIn("ADCPRE=/2 (14MHz @ PCLK2=28MHz",
                      gen_periph.gen_adc("ADC1", 1, "PA1", 28))


class LibraryDomainTests(unittest.TestCase):
    """F-111 (复审 M-3): 域校验下沉库级——import 直调不得绕过守卫"""

    def test_hclk_domain_enforced_in_library(self):
        for bad in (0, 1, 73, -10):
            with self.subTest(hclk=bad):
                for out in (gen_periph.gen_systick(1000, bad),
                            gen_periph.gen_usart("USART1", 115200, "PA9",
                                                 "PA10", bad),
                            gen_periph.gen_adc("ADC1", 1, "PA1", bad),
                            gen_periph.gen_i2c("I2C1", 100000, "PB6",
                                               "PB7", bad),
                            gen_periph.gen_spi("SPI1", 0, "PA4", "PA5",
                                               "PA6", "PA7", 16, bad)):
                    self.assertTrue(out.startswith("/* ERROR"),
                                    f"hclk={bad} 库级必须拒绝: {out[:80]}")
                    # 关键: 不得产出 LOAD=-1 / BRR=0x0000 这类伪合法
                    self.assertNotIn("->LOAD = -1", out)
                    self.assertNotIn("->BRR = 0x0000;", out)

    def test_tim_clk_domain_enforced(self):
        for bad in (0, -5):
            with self.subTest(tim_clk=bad):
                self.assertTrue(gen_periph.gen_pwm(
                    "TIM2", 1, "PA0", 1000, 50, bad, 72).startswith("/* ERROR"))
                self.assertTrue(gen_periph.gen_timer_int(
                    "TIM2", 1, bad, 72).startswith("/* ERROR"))

    def test_tick_wording_honest_at_8mhz(self):
        """F-111 (复审 L-1): 溢出 ERROR 的 tick 文案随 tim_clk 诚实化"""
        out72 = gen_periph.gen_timer_int("TIM2", 1000, 72)
        self.assertIn("(1MHz tick)", out72)   # 72 下逐字节不变
        out8 = gen_periph.gen_timer_int("TIM2", 1000, 8)
        if out8.startswith("/* ERROR"):       # 8MHz 下若仍溢出, 文案须真值
            self.assertNotIn("(1MHz tick)", out8)
            self.assertIn("(111111Hz tick)", out8)


class CliDefaultAndMissingPinsTests(unittest.TestCase):
    """F-111 (复审 L-2/L-3): CLI 缺省路径钉 + spec 缺失钉补齐"""

    def test_cli_without_hclk_flag_equals_explicit_72(self):
        """CLI 缺省钉: 不传 --hclk 的输出 == 显式 --hclk 72 (默认值漂移
        从此有钉——旧 CLI 测试全部显式传值, CLI default 改错无人知)"""
        for argv_tail in (["--type", "usart", "--usart", "USART1",
                           "--baud", "115200"],
                          ["--type", "systick", "--freq", "1000"],
                          ["--type", "adc", "--adc", "ADC1", "--ch", "1",
                           "--pin", "PA1"]):
            with self.subTest(argv=argv_tail):
                r_def = _run_cli(argv_tail)
                r_72 = _run_cli(argv_tail + ["--hclk", "72"])
                self.assertEqual(r_def.returncode, 0, r_def.stdout[:200])
                self.assertEqual(r_def.stdout, r_72.stdout,
                                 "CLI 缺省必须逐字节 == 显式 72")

    def test_cli_usart_hclk8_pclk_annotation(self):
        """spec §5.5 承诺钉: subprocess rc=0 且输出含 PCLK 插值"""
        r = _run_cli(["--type", "usart", "--usart", "USART1", "--baud",
                      "115200", "--hclk", "8"])
        self.assertEqual(r.returncode, 0, r.stdout[:200])
        self.assertIn("PCLK2=8MHz", r.stdout)
        self.assertIn("USART1->BRR = 0x0045;", r.stdout)

    def test_pwm_psc_derived_at_8mhz(self):
        """spec §5.2 承诺钉: pwm PSC 在非 72 下随 hclk 变 (72: PSC=7/ARR=999)"""
        out = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50, None, 8)
        m = re.search(r"PSC=(\d+), ARR=(\d+)", out)
        self.assertIsNotNone(m)
        psc, arr = int(m.group(1)), int(m.group(2))
        self.assertEqual(arr, 999)
        # 8e6/((psc+1)*1000) 必须整除出 1kHz: psc=7 → 8e6/8000=1000 ✓
        self.assertEqual(8_000_000 // ((psc + 1) * (arr + 1)) *
                         ((psc + 1) * (arr + 1)), 8_000_000)
        self.assertEqual(psc, 7)


class PreconditionNoteTests(unittest.TestCase):
    """F-111 (复审 M-4, spec §6): 非默认 hclk 生成物头部回显分频前提;
    hclk=72 不注入 (逐字节兼容优先)"""

    def test_note_present_at_8_absent_at_72(self):
        for fn in (lambda h: gen_periph.gen_usart("USART1", 115200, "PA9", "PA10", h),
                   lambda h: gen_periph.gen_systick(1000, h),
                   lambda h: gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50, None, h),
                   lambda h: gen_periph.gen_timer_int("TIM2", 1, None, h),
                   lambda h: gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7", h),
                   lambda h: gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6", "PA7", 16, h),
                   lambda h: gen_periph.gen_adc("ADC1", 1, "PA1", h)):
            with self.subTest(fn=fn):
                self.assertIn("标准 APB 分频", fn(8))
                self.assertNotIn("标准 APB 分频", fn(72),
                                 "默认路径不得注入 (兼容契约)")


class GenAdcInternalChannelTests(unittest.TestCase):
    """F-219: CH16/17 内部通道必须使能 CR2.TSVREFE, 否则读回恒 0。

    背景 (三号复审历轮列账, 本轮立项): `gen_adc` 生成的 `CR2 = 1` 只置
    ADON。对 CH16 (VREFINT) / CH17 (温度传感器) 而言, 内部通路未使能——
    **转换照常完成、EOC 照常置位、读回恒 0**, 无任何报错。典型 B 类静默。

    真值锚 CMSIS `stm32f103xe.h` ADC_CR2: `TSVREFE_Pos = 23`
    (0x00800000), 且 **F1 无独立 VREFEN 位**——`grep -c ADC_CR2_VREFEN`
    在官方头文件为0, 内部通路由 TSVREFE 一位统一使能 (ref.json ADC1.CR2
    位登记一致: "23": TSVREFE "Temperature sensor and VREFINT enable")。
    故修法是 CR2 初值带上 bit23, **不是** 补一个不存在的 VREFEN。

    外部通道 (CH0~15) 必须**不受影响**: TSVREFE 只对内部通道有意义, 且
    RM0008 §11.5 内部通道不受外部触发配置影响——本组钉住外部路径逐字节
    不变, 防"修内部顺手改了外部"。
    """

    def _internal(self, ch):
        return gen_periph.gen_adc("ADC1", ch, "PA1")

    def test_ch16_enables_tsvrefe(self):
        """CH16 (VREFINT): CR2 初值须含 TSVREFE(bit23) + ADON。"""
        out = self._internal(16)
        self.assertRegex(
            out, r"ADC1->CR2\s*=\s*[^;]*\(1UL << 23\)",
            f"CH16 生成物未使能 TSVREFE:\n{out}")

    def test_ch17_enables_tsvrefe(self):
        """CH17 (温度传感器): 同 CH16。"""
        out = self._internal(17)
        self.assertRegex(
            out, r"ADC1->CR2\s*=\s*[^;]*\(1UL << 23\)",
            f"CH17 生成物未使能 TSVREFE:\n{out}")

    def test_tsvrefe_bit_matches_official_23(self):
        """位号钉: TSVREFE 必须是 bit23 (0x00800000), 移位写错则静默开别的位。"""
        out = self._internal(16)
        # 提取 TSVREFE 的移位量, 断言为 23
        m = re.search(r"\(1UL << (\d+)\)[^\n]*TSVREFE|TSVREFE[^\n]*?\(1UL << (\d+)\)",
                      out)
        self.assertIsNotNone(m, f"生成物未见 TSVREFE 置位语句:\n{out}")
        shift = int(m.group(1) or m.group(2))
        self.assertEqual(
            shift, 23,
            f"TSVREFE 移位量应为 23 (官方 ADC_CR2_TSVREFE_Pos), 实得 {shift}")

    def test_external_channels_unchanged(self):
        """CH0~15 逐字节不变——修内部通道不得波及外部通道。"""
        for ch in (0, 1, 5, 15):
            with self.subTest(ch=ch):
                out = self._internal(ch)
                self.assertNotIn(
                    "TSVREFE", out,
                    f"外部通道 CH{ch} 不该出现 TSVREFE")
                self.assertIn("ADC1->CR2 = 1;", out)

    def test_no_phantom_vrefen_bit(self):
        """F1 无 VREFEN 位——若生成物出现 VREFEN 说明按 F2/F4 误改。"""
        for ch in (16, 17):
            with self.subTest(ch=ch):
                self.assertNotIn(
                    "VREFEN", self._internal(ch),
                    "F1 的 ADC_CR2 无 VREFEN 位 (官方头文件 grep 为 0), "
                    "内部通路由 TSVREFE 一位使能")


if __name__ == "__main__":
    unittest.main()
