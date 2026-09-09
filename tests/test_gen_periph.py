r"""gen_periph 代码生成器回归套件 (F-071) — 0% 覆盖模块的首批补齐。

背景: 2026-09-08 全仓 coverage 实测 scripts/ 6,664 语句仅 31%, 其中
`gen_periph.py` 528 语句 0% —— 而它是给 AI 产出寄存器级 C 代码的唯一入口,
生成物会被直接粘进固件; 0% 覆盖 = 生成器写错 bit 位移也没人知道。

覆盖策略 (只钉 nurses 行为, 不动生产代码):
  1. 纯函数优先: pin_* helpers 是全部生成函数的地基, 逐条钉;
  2. 每个 gen_* 走"平凡路径 + 至少一个分支/边界": 总线选择 (APB1/APB2)、
     寄存器选择 (CRL/CRH、SMPR1/2、CCMR1/2)、分频/波特率换算、错误分支;
  3. 已知缺陷按本仓 xfail 纪律登记为 expectedFailure (欠债白纸黑字),
     修好后它们会 XPASS, 届时必须翻转重跑 —— F-071 登记的三例已由
     F-074 (ENR 双写) / F-075 (usart CRH) / F-076 (BRR 进位) 全部修复
     翻转为常规断言, GenKnownGapTests 类随之清空移除。

不覆盖: gen_doc 的真实 doxygen 排版细节 (随时可调), main() 的 argparse
帮助文本。所有断言取值为 2026-09-08 在 HEAD 8b8f2ba 上的实跑输出。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class PinHelperTests(unittest.TestCase):
    """引脚解析 helpers —— 所有生成函数的位移/寄存器选择都依赖它们"""

    def test_pin_port_single_and_double_digit(self):
        self.assertEqual(gen_periph.pin_port("PA0"), "A")
        self.assertEqual(gen_periph.pin_port("PC13"), "C")
        self.assertEqual(gen_periph.pin_port("PB10"), "B")

    def test_pin_num_supports_multidigit_and_missing_digit(self):
        self.assertEqual(gen_periph.pin_num("PA0"), 0)
        self.assertEqual(gen_periph.pin_num("PC13"), 13)
        self.assertEqual(gen_periph.pin_num("PB10"), 10)
        self.assertEqual(gen_periph.pin_num("PX"), 0)  # 无数字 → 0, 不抛

    def test_pin_cr_reg_low_bank_and_high_bank(self):
        self.assertEqual(gen_periph.pin_cr_reg("PA7"), "CRL")
        self.assertEqual(gen_periph.pin_cr_reg("PA8"), "CRH")
        self.assertEqual(gen_periph.pin_cr_reg("PC13"), "CRH")

    def test_pin_cr_shift_wraps_at_pin8(self):
        # pin8 归 CRH 且位移回到 0; pin13 → (13%8)*4 = 20
        self.assertEqual(gen_periph.pin_cr_shift("PA0"), 0)
        self.assertEqual(gen_periph.pin_cr_shift("PA7"), 28)
        self.assertEqual(gen_periph.pin_cr_shift("PA8"), 0)
        self.assertEqual(gen_periph.pin_cr_shift("PC13"), 20)


class GenGpioTests(unittest.TestCase):

    def test_pc13_out_pp_50mhz_full_output(self):
        out = gen_periph.gen_gpio("PC13", "out-pp-50mhz")
        self.assertEqual(out.splitlines(), [
            "/* PC13 — 通用推挽输出 50MHz */",
            "RCC->APB2ENR |= RCC_APB2ENR_IOPCEN;",
            "__DSB();",
            "GPIOC->CRH &= ~(0xFUL << 20);",
            "GPIOC->CRH |=  (0x3UL << 20);",
        ])

    def test_all_documented_modes_map_to_expected_cnf_mode_bits(self):
        expected = {
            "out-pp-50mhz": "0x3", "out-pp-2mhz": "0x2", "out-od-50mhz": "0x7",
            "af-pp-50mhz": "0xB", "af-od-50mhz": "0xF", "in-floating": "0x4",
            "in-pullup": "0x8", "in-analog": "0x0",
        }
        for mode, bits in expected.items():
            with self.subTest(mode=mode):
                out = gen_periph.gen_gpio("PA5", mode)
                self.assertIn(f"GPIOA->CRL |=  ({bits}UL << 20);", out)

    def test_low_pin_uses_crl_high_pin_uses_crh(self):
        self.assertIn("GPIOA->CRL", gen_periph.gen_gpio("PA5", "in-analog"))
        self.assertIn("GPIOA->CRH", gen_periph.gen_gpio("PA9", "in-analog"))

    def test_unknown_port_falls_back_to_generic_names(self):
        # 知识库只有 A/B/C; D 端口按 GPIO_BASE/clock 的 fallback 模板推导
        out = gen_periph.gen_gpio("PD3", "out-pp-50mhz")
        self.assertIn("GPIOD->CRL", out)
        self.assertIn("RCC_APB2ENR_IOPDEN", out)

    def test_unknown_mode_defaults_to_0x3_and_echoes_raw_mode(self):
        out = gen_periph.gen_gpio("PD3", "weird-mode")
        self.assertIn("/* PD3 — weird-mode */", out)
        self.assertIn("GPIOD->CRL |=  (0x3UL << 12);", out)

    def test_in_pullup_sets_odr_bit_f087(self):
        """F-087 缺陷 A: CNF=10/MODE=00 时上下拉方向由 ODR 决定, 复位 ODR=0
        → 只写 CRL 位不置 ODR 实际是下拉。上拉必须显式置 ODR 对应位。"""
        out = gen_periph.gen_gpio("PA0", "in-pullup")
        self.assertIn("GPIOA->ODR |= (1UL << 0);", out)
        self.assertIn("GPIOA->CRL |=  (0x8UL << 0);", out)

    def test_in_pullup_high_pin_uses_crh_and_odr(self):
        out = gen_periph.gen_gpio("PB9", "in-pullup")
        self.assertIn("GPIOB->CRH |=  (0x8UL << 4);", out)
        self.assertIn("GPIOB->ODR |= (1UL << 9);", out)

    def test_non_pull_modes_do_not_touch_odr_f087(self):
        """反向钉: ODR 置位仅属于 in-pullup, 其他模式不得波及"""
        for mode in ("out-pp-50mhz", "in-floating", "in-analog"):
            with self.subTest(mode=mode):
                self.assertNotIn("->ODR", gen_periph.gen_gpio("PA0", mode))


class GenSystickTests(unittest.TestCase):

    def test_1khz_divisor_of_72mhz(self):
        out = gen_periph.gen_systick(1000)
        self.assertIn("SysTick->LOAD = 71999;", out)
        self.assertIn("/* SysTick — 1000Hz (1000us interval), 72MHz core clock */", out)
        self.assertIn("SysTick->CTRL = SysTick_CTRL_ENABLE | SysTick_CTRL_TICKINT "
                      "| SysTick_CTRL_CLKSOURCE;", out)
        self.assertIn("void SysTick_Handler(void) {", out)
        self.assertIn("void delay_ms(uint32_t ms) {", out)

    def test_non_divisor_returns_error_comment_instead_of_silent_wrong_value(self):
        # 72MHz/7 非整数 —— 生成器宁可报错也不给错误 LOAD
        out = gen_periph.gen_systick(7)
        self.assertEqual(
            out, "/* ERROR: 72MHz / 7 is not an integer. Choose a divisor of 72MHz. */")

    def test_handler_increments_tick_ms_f087(self):
        """F-087 缺陷 B: Handler 空体 + delay_ms 依赖 tick_ms → 首次调用
        delay_ms 永久死循环。ISR 必须递增 tick_ms (F-080 同族不变量)。"""
        out = gen_periph.gen_systick(1000)
        handler_body = out.split("void SysTick_Handler(void) {")[1].split("}")[0]
        # 断言的是递增语句本身（tick_ms++ / tick_ms += 1），不是注释里的字面量
        self.assertRegex(handler_body, r"tick_ms\+\+|tick_ms\s*\+=",
                         "SysTick_Handler 体内必须有 tick_ms 递增语句")

    def test_tick_ms_declared_before_handler_f087(self):
        """F-087 伴随约束: tick_ms 声明必须在 SysTick_Handler 定义之前
        (生成物是可独立编译的片段, 先用后声明编译即失败)。"""
        out = gen_periph.gen_systick(1000)
        self.assertLess(out.index("static volatile uint32_t tick_ms;"),
                        out.index("void SysTick_Handler(void) {"))


class GenUsartTests(unittest.TestCase):

    def test_usart1_on_apb2_72mhz_brr_0x271_at_115200(self):
        out = gen_periph.gen_usart("USART1", 115200, "PA9", "PA10")
        self.assertIn("RCC->APB2ENR |= RCC_APB2ENR_USART1EN;", out)
        self.assertIn("* PCLK2=72MHz, BRR=0x0271 (39.1/16)", out)
        self.assertIn("USART1->BRR = 0x0271;", out)   # 39 + 1/16 = 39.0625
        self.assertIn("int fputc(int ch, FILE *f) {", out)

    def test_usart2_on_apb1_36mhz_brr_0xea6_at_9600(self):
        out = gen_periph.gen_usart("USART2", 9600, "PA2", "PA3")
        self.assertIn("RCC->APB1ENR |= RCC_APB1ENR_USART2EN;", out)
        self.assertIn("* PCLK1=36MHz, BRR=0x0EA6 (234.6/16)", out)
        self.assertIn("USART2->BRR = 0x0EA6;", out)   # 234 + 6/16 = 234.375

    def test_gpio_clock_lines_deduplicated_and_sorted_per_port(self):
        same = gen_periph.gen_usart("USART1", 115200, "PA9", "PA10")
        clk = [l for l in same.splitlines() if "APB2ENR_IOP" in l]
        self.assertEqual(clk, ["RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;"])

        diff = gen_periph.gen_usart("USART1", 115200, "PA9", "PB7")
        clk = [l for l in diff.splitlines() if "APB2ENR_IOP" in l]
        self.assertEqual(clk, ["RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;",
                               "RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;"])

    def test_tx_af_pp_and_rx_floating_patterns_present(self):
        out = gen_periph.gen_usart("USART1", 115200, "PA9", "PA10")
        self.assertIn("GPIOA->CRH |=  (0xBUL << 4);", out)   # TX=PA9 AF-PP
        self.assertIn("GPIOA->CRH |=  (0x4UL << 8);", out)   # RX=PA10 浮空

    def test_brr_fraction_carry_rounds_into_mantissa(self):
        """F-076 修复钉: fraction 舍入到 16 必须进位到 mantissa。

        baud=1377 @72MHz: div=3267.974 → m=3267, f=16 → 进位 3268/0 =
        3268<<4 = 0xCC40; 旧式 (m<<4)|f 在奇数 m 下 bit4 已被占用,
        进位被静默丢弃 (0xCC30 = 3267.0)。
        订正: F-071 旧段与已知缺口 docstring 曾写 "应 0xCB00" 为算术笔误,
        以本断言为准。"""
        out = gen_periph.gen_usart("USART1", 1377, "PA9", "PA10")
        self.assertIn("USART1->BRR = 0xCC40;", out)
        # 进位后整数分频值不得再携带非零小数位
        self.assertIn("BRR=0xCC40 (3268.0/16)", out)

    def test_low_pins_use_crl_high_pins_use_crh(self):
        """F-075 修复钉: CRH 硬编码曾把 PA2 的位移落在 PA10 的字段上。"""
        low = gen_periph.gen_usart("USART2", 9600, "PA2", "PA3")
        self.assertIn("GPIOA->CRL |=  (0xBUL << 8);", low)   # TX=PA2 AF-PP
        self.assertIn("GPIOA->CRL |=  (0x4UL << 12);", low)  # RX=PA3 浮空
        gpio_lines = [l for l in low.splitlines() if l.startswith("GPIO")]
        self.assertTrue(all("CRL" in l for l in gpio_lines),
                        f"低引脚 (PA2/PA3) 的 GPIO 行不得再出现 CRH: {gpio_lines}")


class GenPwmTests(unittest.TestCase):

    def test_exact_psc_arr_pair_selected_for_1khz(self):
        out = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50)
        self.assertIn(" * TIM_CLK=72MHz, PSC=71, ARR=999, CCR1=500 ", out)
        self.assertIn("TIM2->PSC = 71;", out)
        self.assertIn("TIM2->ARR = 999;", out)
        self.assertIn("TIM2->CCR1 = 500;", out)
        self.assertIn("TIM2->CR1 = (1<<7) | 1;", out)   # ARPE + CEN

    def test_channel12_use_ccmr1_channel34_use_ccmr2(self):
        out1 = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50)
        self.assertIn("TIM2->CCMR1 = (6<<4) | (1<<3);", out1)
        self.assertIn("TIM2->CCER  |= (1<<0);", out1)

        out3 = gen_periph.gen_pwm("TIM2", 3, "PA2", 1000, 25)
        self.assertIn("TIM2->CCMR2 = (6<<4) | (1<<3);", out3)
        self.assertIn("TIM2->CCER  |= (1<<8);", out3)

        out4 = gen_periph.gen_pwm("TIM2", 4, "PA3", 1000, 25)
        self.assertIn("TIM2->CCMR2 = (6<<12) | (1<<11);", out4)
        self.assertIn("TIM2->CCER  |= (1<<12);", out4)

    def test_empty_pin_autodetected_from_timer_channel_map(self):
        # pin="" → 走 TIM_CH_PINS 默认复用映射; 显式 pin 优先于映射
        self.assertIn("/* 2. GPIO — PA2 复用推挽 50MHz */",
                      gen_periph.gen_pwm("TIM2", 3, "", 1000, 25))
        self.assertIn("/* 2. GPIO — PB6 复用推挽 50MHz */",
                      gen_periph.gen_pwm("TIM4", 1, "", 1000, 25))
        self.assertIn("/* 2. GPIO — PC13 复用推挽 50MHz */",
                      gen_periph.gen_pwm("TIM2", 1, "PC13", 1000, 25))

    def test_unknown_timer_falls_back_to_generic_clock_bit_and_crh(self):
        out = gen_periph.gen_pwm("TIM9", 1, "PC13", 1000, 50)
        self.assertIn("RCC->APB1ENR |= RCC_APB1ENR_TIM9EN;", out)
        self.assertIn("GPIOC->CRH |=  (0xBUL << 20);", out)

    def test_tim1_clock_enable_is_on_apb2(self):
        """F-077 修复钉: TIM1 挂 APB2, 旧版两个 TIM 生成器都硬编码 APB1ENR。"""
        out = gen_periph.gen_pwm("TIM1", 1, "PA8", 1000, 50)
        self.assertIn("RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;", out)
        self.assertNotIn("RCC->APB1ENR", out)

    def test_non_integer_psc_reports_actual_frequency_in_note(self):
        # 7000Hz 在候选 ARR 表内无整除 PSC → 走兜底并如实标注实际频率
        out = gen_periph.gen_pwm("TIM2", 1, "PA0", 7000, 50)
        self.assertIn("(target 7000Hz, actual ~7200Hz)", out)
        self.assertIn("TIM2->PSC = 9;", out)

    def test_duty_boundaries_zero_and_full(self):
        out0 = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 0)
        self.assertIn("TIM2->CCR1 = 0;", out0)
        out100 = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 100)
        self.assertIn("TIM2->CCR1 = 1000;", out100)   # == ARR+1, 全开


class GenAdcTests(unittest.TestCase):

    def test_channels_0_to_9_use_smpr2(self):
        out = gen_periph.gen_adc("ADC1", 1, "PA1")
        self.assertIn("ADC1->SMPR2 |= (5UL << 3);", out)
        self.assertIn("ADC1->SQR3 = 1;", out)
        self.assertIn("RCC->APB2ENR |= RCC_APB2ENR_ADC1EN | RCC_APB2ENR_IOPAEN;", out)

    def test_channel_10_and_above_use_smpr1_with_10_offset_shift(self):
        self.assertIn("ADC1->SMPR1 |= (5UL << 0);", gen_periph.gen_adc("ADC1", 10, "PC0"))
        self.assertIn("ADC2->SMPR1 |= (5UL << 15);", gen_periph.gen_adc("ADC2", 15, "PC5"))

    def test_generated_helpers_and_analog_input_config(self):
        out = gen_periph.gen_adc("ADC1", 1, "PA1")
        self.assertIn("GPIOA->CRL &= ~(0xFUL << 4);", out)
        self.assertIn("static uint16_t adc_read_ch1(void) {", out)
        self.assertIn("static uint32_t adc_to_mv(uint16_t val) {", out)
        self.assertIn("return (uint32_t)val * 3300 / 4096;", out)

    def test_high_pin_adc_channel_uses_crh(self):
        self.assertIn("GPIOB->CRH &= ~(0xFUL << 0);", gen_periph.gen_adc("ADC1", 8, "PB8"))

    def test_adclock_prescaler_set_within_14mhz_limit_f087(self):
        """F-087 缺陷 C: 默认 ADCPRE=/2 → 36MHz 超出 KB 明文的 14MHz 上限。
        生成物必须先清后置 CFGR 的 ADCPRE 字段 (位 14:15)。"""
        out = gen_periph.gen_adc("ADC1", 1, "PA1")
        self.assertIn("RCC->CFGR", out)
        self.assertIn("ADCPRE", out)
        # 先清后置语义: 必须有 &= ~ 掩码行, 不得整体赋值
        self.assertIn("&= ~", out)
        self.assertNotIn("RCC->CFGR =", out)

    def test_adclock_div6_selects_binary_10_f087(self):
        """ADCPRE=10 (bit15=1) → PCLK2/6 = 12MHz ≤ 14MHz"""
        out = gen_periph.gen_adc("ADC1", 1, "PA1")
        self.assertIn("(3UL << 14)", out)   # 清 14:15 两位掩码 0x3<<14
        self.assertIn("(2UL << 14)", out)   # 置 10b = /6


class GenTimerIntTests(unittest.TestCase):

    def test_tim2_1ms_period(self):
        out = gen_periph.gen_timer_int("TIM2", 1, 72)
        self.assertIn("NVIC->ISER[0] = (1UL << 28);  // TIM2_IRQn = 28", out)
        self.assertIn("TIM2->PSC = 71;", out)
        self.assertIn("TIM2->ARR = 999;", out)
        self.assertIn("void TIM2_IRQHandler(void) {", out)

    def test_irq_number_mapping_and_unknown_timer_defaults(self):
        self.assertIn("NVIC->ISER[0] = (1UL << 25);",
                      gen_periph.gen_timer_int("TIM1", 10, 72))
        self.assertIn("NVIC->ISER[0] = (1UL << 30);",
                      gen_periph.gen_timer_int("TIM4", 1, 72))
        # 未知定时器: IRQ 落默认 28, 时钟位按 {timer}EN 模板推导
        unknown = gen_periph.gen_timer_int("TIM9", 1, 72)
        self.assertIn("NVIC->ISER[0] = (1UL << 28);  // TIM9_IRQn = 28", unknown)
        self.assertIn("RCC->APB1ENR |= RCC_APB1ENR_TIM9EN;", unknown)

    def test_tim1_clock_enable_is_on_apb2(self):
        """F-077 修复钉: TIM1 是 APB2 外设 (RM0008), 旧版产出 APB1ENR_TIM1EN
        — CMSIS 头无此宏, 编译失败; 或被 AI 顺手改成使能别的位。"""
        out = gen_periph.gen_timer_int("TIM1", 1, 72)
        self.assertIn("RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;", out)
        self.assertNotIn("APB1ENR", out)

    def test_custom_timer_clock_scales_arr(self):
        # 36MHz → 同样 1ms 目标下 ARR 减半量级
        self.assertIn("TIM2->ARR = 499;", gen_periph.gen_timer_int("TIM2", 1, 36))


class GenI2cTests(unittest.TestCase):

    def test_standard_mode_100k_ccr_and_trise(self):
        out = gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7")
        self.assertIn(" * CCR=0x0B4 (180), TRISE=0x25 (37)", out)
        self.assertIn("I2C1->CR2 = 36;", out)
        self.assertIn("I2C1->CCR = 0x0B4;", out)          # 无 F/S bit
        self.assertIn("I2C1->TRISE = 37;", out)
        self.assertIn("I2C1->CR1 = 1;", out)
        self.assertIn("GPIOB->CRL |=  (0xFUL << 24);", out)  # PB6 AF-OD
        self.assertIn("static error_chain_t i2c1_write(", out)

    def test_fast_mode_400k_sets_fs_bit_and_shorter_trise(self):
        out = gen_periph.gen_i2c("I2C2", 400000, "PB10", "PB11")
        self.assertIn(" * CCR=0x01E (30), TRISE=0x0B (11)", out)
        self.assertIn("I2C2->CCR = 0x01E | (1<<15);", out)
        self.assertIn("I2C2->TRISE = 11;", out)
        self.assertIn("GPIOB->CRH |=  (0xFUL << 8);", out)  # PB10 AF-OD

    def test_unknown_peripheral_and_unsupported_speed_return_error(self):
        self.assertEqual(gen_periph.gen_i2c("I2C3", 100000, "PB6", "PB7"),
                         "/* ERROR: Unknown I2C peripheral I2C3 */")
        self.assertEqual(gen_periph.gen_i2c("I2C1", 10000, "PB6", "PB7"),
                         "/* ERROR: Unsupported I2C speed 10000Hz. "
                         "Supported: 100000, 400000 */")

    def test_errata_warning_is_emitted_for_f103_i2c(self):
        # 生成器必须自带 F103 I2C errata 免责声明 (作者即有此约定)
        self.assertIn("known errata", gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7"))


class GenSpiTests(unittest.TestCase):

    def test_spi1_mode0_apb2_and_cr1_value(self):
        out = gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6", "PA7", 16)
        self.assertIn("RCC->APB2ENR |= RCC_APB2ENR_SPI1EN;", out)
        self.assertIn("* PCLK=72MHz, BR[2:0]=3 (/ 16)", out)
        self.assertIn(" * SPI1 — Mode 0 (CPOL=0,CPHA=0), 4500kHz", out)
        self.assertIn("SPI1->CR1 = 0x001C | (1<<9) | (1<<8);", out)  # BR=3, MSTR
        self.assertIn("#define SPI1_CS_LOW()  GPIOA->BRR = (1UL << 4)", out)

    def test_spi2_mode3_uses_apb1_and_sets_cpol_cpha(self):
        out = gen_periph.gen_spi("SPI2", 3, "PB12", "PB13", "PB14", "PB15", 256)
        self.assertIn("RCC->APB1ENR |= RCC_APB1ENR_SPI2EN;", out)
        self.assertIn(" * SPI2 — Mode 3 (CPOL=1,CPHA=1), 140kHz", out)
        self.assertIn("SPI2->CR1 = 0x003F | (1<<9) | (1<<8);", out)  # BR=7 + CPOL + CPHA

    def test_port_clock_lines_deduplicated_and_sorted(self):
        out = gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6", "PA7", 16)
        self.assertEqual([l for l in out.splitlines() if "APB2ENR_IOP" in l],
                         ["RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;"])
        multi = gen_periph.gen_spi("SPI1", 0, "PB0", "PA5", "PA6", "PA7", 16)
        self.assertEqual([l for l in multi.splitlines() if "APB2ENR_IOP" in l],
                         ["RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;",
                          "RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;"])

    def test_miso_configured_as_floating_input_while_sck_mosi_af_pp(self):
        out = gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6", "PA7", 16)
        self.assertIn("GPIOA->CRL |=  (0xBUL << 20);", out)   # SCK AF-PP
        self.assertIn("GPIOA->CRL |=  (0x4UL << 24);", out)   # MISO 浮空
        self.assertIn("GPIOA->CRL |=  (0x3UL << 16);", out)   # NSS 推挽

    def test_unknown_peripheral_error_and_unknown_baud_div_defaults_to_16(self):
        self.assertEqual(
            gen_periph.gen_spi("SPI3", 0, "PA4", "PA5", "PA6", "PA7", 16),
            "/* ERROR: Unknown SPI peripheral SPI3 */")
        self.assertIn("* PCLK=72MHz, BR[2:0]=3 (/ 16)",
                      gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6", "PA7", 999))

class GenDocTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_existing_peripheral_writes_both_artifacts(self):
        ret = gen_periph.gen_doc("I2C1", self.tmp)
        self.assertTrue(ret.startswith("Generated:"))
        self.assertIn("i2c1_doc.h", ret)
        self.assertIn("i2c1_ref.md", ret)

        dox = os.path.join(self.tmp, "i2c1_doc.h")
        md = os.path.join(self.tmp, "i2c1_ref.md")
        self.assertTrue(os.path.isfile(dox))
        self.assertTrue(os.path.isfile(md))

        dox_text = open(dox, encoding="ascii", errors="replace").read()
        self.assertIn("@file i2c1_doc.h", dox_text)
        self.assertIn("Base Address: 0x40005400", dox_text)
        self.assertIn("Bus: APB1", dox_text)

        md_text = open(md, encoding="utf-8").read()
        self.assertIn("# I2C1 Peripheral Reference", md_text)
        self.assertIn("- **Base**: 0x40005400 | **Bus**: APB1", md_text)
        self.assertIn("## Registers", md_text)
        self.assertIn("| CCR | 0x1C |", md_text)
        self.assertIn("## Dependencies", md_text)
        # F-074 修复后: 完整正确形态 (修复前产出 RCC_APB1ENRENR)
        self.assertIn("- Clock: RCC_APB1ENR bit 21 (I2C1EN)", md_text)
        self.assertIn("- Pins: SCL=B6, SDA=B7", md_text)
        self.assertIn("- DMA: TX=DMA1_CH6, RX=DMA1_CH7", md_text)
        self.assertIn("- IRQ: I2C1_EV_IRQn = 31", md_text)

    def test_unknown_peripheral_does_not_write_files(self):
        ret = gen_periph.gen_doc("NOPE_PERIPH", self.tmp)
        self.assertEqual(ret, "Error: NOPE_PERIPH not found in stm32f103-ref.json")
        self.assertEqual(os.listdir(self.tmp), [])

    def test_relationships_only_entry_is_still_documented(self):
        """peripherals 缺席但 _relationships 在 → 走 base/bus 兜底分支"""
        ref = {"peripherals": {}, "_relationships": {
            "USART9": {
                "bus": "APB2", "base": "0x40013800",
                "clock": {"rcc_register": "APB2ENR", "rcc_bit": 14,
                          "rcc_bit_name": "USART9EN"},
                "pins": {"TX": {"port": "A", "pin": 9}},
                "dma": {"TX": "DMA1_CH4"},
                "irq": {"name": "USART9_IRQn", "number": 37},
            }}}
        with mock.patch.object(gen_periph, "load_ref", return_value=ref):
            ret = gen_periph.gen_doc("USART9", self.tmp)
        self.assertTrue(ret.startswith("Generated:"))
        md_text = open(os.path.join(self.tmp, "usart9_ref.md"), encoding="utf-8").read()
        self.assertIn("- **Base**: 0x40013800 | **Bus**: APB2", md_text)
        self.assertIn("- Clock: RCC_APB2ENR", md_text)
        self.assertIn("bit 14 (USART9EN)", md_text)
        self.assertIn("- Pins: TX=A9", md_text)
        self.assertIn("- DMA: TX=DMA1_CH4", md_text)
        self.assertIn("- IRQ: USART9_IRQn = 37", md_text)
        # 无 registers/recipes → 表格只有表头, 无 Code Recipes 段
        self.assertIn("| Register | Offset | Description | Key Fields |", md_text)
        self.assertNotIn("## Code Recipes", md_text)

    def test_output_dir_defaults_to_project_modules_when_omitted(self):
        """不传 out_dir 时落到 find_project_root(cwd)/modules/<lower>/"""
        proj = tempfile.mkdtemp()
        os.makedirs(os.path.join(proj, ".workbench"), exist_ok=True)
        with open(os.path.join(proj, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({}, f)
        try:
            with mock.patch.object(gen_periph.os, "getcwd", return_value=proj):
                with mock.patch.object(gen_periph, "find_project_root",
                                       return_value=proj):
                    ret = gen_periph.gen_doc("I2C1", "")
            self.assertTrue(ret.startswith("Generated:"))
            self.assertTrue(os.path.isfile(
                os.path.join(proj, "modules", "i2c1", "i2c1_ref.md")))
        finally:
            shutil.rmtree(proj, ignore_errors=True)


class MainCliDispatchTests(unittest.TestCase):
    """main() 的参数分发与必填校验 (argparse 层, 不 subprocess 起进程)"""

    def _run(self, argv):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["gen_periph.py"] + argv):
            with redirect_stdout(buf):
                gen_periph.main()
        return buf.getvalue()

    def test_gpio_type_requires_pin(self):
        with mock.patch.object(sys, "argv",
                               ["gen_periph.py", "--type", "gpio"]):
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    gen_periph.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_doc_type_requires_periph(self):
        with mock.patch.object(sys, "argv",
                               ["gen_periph.py", "--type", "doc"]):
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    gen_periph.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_pwm_type_requires_pin_and_autodetects_from_timer_channel(self):
        # 默认 timer/ch (TIM2 CH1) 命中 TIM_CH_PINS 会自动补 pin, 不报错;
        # 映射外的组合 (TIM9 CH1) 才走到"缺 --pin"退出
        with mock.patch.object(sys, "argv",
                               ["gen_periph.py", "--type", "pwm",
                                "--timer", "TIM9", "--ch", "1"]):
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    gen_periph.main()
        self.assertEqual(ctx.exception.code, 1)

        out = self._run(["--type", "pwm", "--timer", "TIM2", "--ch", "1",
                         "--freq", "1000", "--duty", "50"])
        self.assertIn("TIM2 CH1 PWM — PA0", out)

    def test_adc_type_requires_pin(self):
        with mock.patch.object(sys, "argv",
                               ["gen_periph.py", "--type", "adc"]):
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    gen_periph.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_each_type_dispatch_reaches_its_generator(self):
        cases = [
            (["--type", "gpio", "--pin", "PC13"], "GPIOC->CRH"),
            (["--type", "usart", "--usart", "USART1"], "USART1->BRR"),
            (["--type", "adc", "--adc", "ADC1", "--ch", "1", "--pin", "PA1"],
             "ADC1->SMPR2"),
            (["--type", "systick", "--freq", "1000"], "SysTick->LOAD = 71999;"),
            (["--type", "timer-int", "--timer", "TIM2", "--period-ms", "1"],
             "TIM2_IRQHandler"),
            (["--type", "i2c", "--i2c", "I2C1", "--speed", "100000"],
             "I2C1->CCR"),
            (["--type", "spi", "--spi", "SPI1", "--spi-mode", "0"],
             "SPI1->CR1"),
        ]
        for argv, needle in cases:
            with self.subTest(type=argv[1]):
                self.assertIn(needle, self._run(argv))

    def test_doc_type_writes_and_reports_paths(self):
        tmp = tempfile.mkdtemp()
        try:
            out = self._run(["--type", "doc", "--periph", "I2C1", "--out-dir", tmp])
            self.assertIn("Generated:", out)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "i2c1_ref.md")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
