r"""生成器数值扫描测试 (F-079) — 从"点断言"升级为"性质断言"。

F-071 的点断言钉住了代表性数值 (BRR 0x271@115200, PWM PSC=71/ARR=999@1kHz),
但连续域回归 (改舍入策略 / 改候选 ARR 表) 可以绕过孤点。本文件扫:

  1. USART BRR: 标准波特率全表 × 双总线 (APB2=72MHz / APB1=36MHz), 性质——
     a) 装箱值与真实分频数的偏差 ≤ 半 LSB (1/32): 正确舍入的紧上界,
        与速率无关; F-076 的进位缺陷在这条性质下无处遁形;
     b) 换算回的实际波特率误差 ≤ 2% (UART 实用容限)。
  2. PWM 频率扫描 1..2000Hz + 高频样本: 性质——
     a) 输出无 "actual" 旁注 ⇒ TIM_CLK 必须精确整除出目标频率
        (freq*(PSC+1)*(ARR+1) == 72e6, 纯整数断言);
     b) 有旁注 ⇒ 旁注里的 actual 必须与按 PSC/ARR 重算的实测值一致
        (生成器不许声称它产不出的频率);
     c) PSC/ARR 都在 16 位寄存器范围内。

全部解析自生成输出 (黑盒契约), 不 import 生成器内部变量。
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402

STANDARD_BAUDS = (1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400,
                  57600, 76800, 115200, 230400, 460800, 921600)
PCLK = {"USART1": 72_000_000, "USART2": 36_000_000}
TIM_CLK = 72_000_000


def _brr_divisor(usart_out: str) -> int:
    m = re.search(r"->BRR = 0x([0-9A-Fa-f]+);", usart_out)
    if not m:
        raise AssertionError("生成输出中未找到 BRR 装箱行")
    brr = int(m.group(1), 16)
    return (brr >> 4) + (brr & 0xF) / 16


class UsartBrrSweepTests(unittest.TestCase):
    """标准波特率全表: 舍入性质 + 实用容限"""

    def test_standard_bauds_rounding_within_half_lsb(self):
        for baud in STANDARD_BAUDS:
            for usart, pclk in PCLK.items():
                with self.subTest(usart=usart, baud=baud):
                    out = gen_periph.gen_usart(usart, baud, "PA9", "PA10")
                    div_true = pclk / (16 * baud)
                    div_boxed = _brr_divisor(out)
                    # 半 LSB = 1/32: 正确舍入的紧上界 (F-076 进位缺陷在此现形)
                    self.assertLessEqual(
                        abs(div_boxed - div_true), 1 / 32,
                        f"{usart}@{baud}: 装箱分频 {div_boxed} 偏离真实值 "
                        f"{div_true:.6f} 超过半 LSB")
                    actual_baud = pclk / (16 * div_boxed)
                    self.assertLessEqual(
                        abs(actual_baud - baud) / baud, 0.02,
                        f"{usart}@{baud}: 实际波特率 {actual_baud:.0f} "
                        f"误差超 2%")

    def test_low_baud_edge_1200_on_slow_bus(self):
        # 36MHz/1200 → div=1875.0 整数: 边界样本, 装箱必须精确
        out = gen_periph.gen_usart("USART2", 1200, "PA2", "PA3")
        self.assertEqual(_brr_divisor(out), 1875.0)


class PwmFrequencySweepTests(unittest.TestCase):
    """1..2000Hz 全扫 + 高频样本: 整除精确性 / 旁注诚实性 / 16 位范围"""

    FREQS = list(range(1, 2001)) + [2500, 3000, 5000, 10000, 20000, 50000]

    def test_pwm_frequency_sweep(self):
        failures = []
        for freq in self.FREQS:
            out = gen_periph.gen_pwm("TIM2", 1, "PA0", freq, 50)
            psc = int(re.search(r"->PSC = (\d+);", out).group(1))
            arr = int(re.search(r"->ARR = (\d+);", out).group(1))
            note = re.search(r"\(target (\d+)Hz, actual ~(\d+)Hz\)", out)
            if not (0 <= psc <= 65535 and 0 <= arr <= 65535):
                failures.append(f"{freq}Hz: PSC={psc}/ARR={arr} 超出 16 位")
                continue
            achieved = TIM_CLK / ((psc + 1) * (arr + 1))
            if note is None:
                # 无旁注 = 声称精确: freq*(PSC+1)*(ARR+1) 必须整除 TIM_CLK
                if freq * (psc + 1) * (arr + 1) != TIM_CLK:
                    failures.append(
                        f"{freq}Hz: 无旁注但 PSC={psc}/ARR={arr} 实际产出 "
                        f"{achieved:.3f}Hz — 生成器声称了它产不出的频率")
            else:
                target, actual_note = int(note.group(1)), int(note.group(2))
                if target != freq:
                    failures.append(f"{freq}Hz: 旁注 target={target} 不自洽")
                if abs(achieved - actual_note) > 0.5:
                    failures.append(
                        f"{freq}Hz: 旁注 actual~{actual_note} 与重算值 "
                        f"{achieved:.3f} 不一致")
        self.assertEqual(
            failures, [],
            f"PWM 频率扫描发现 {len(failures)} 处性质违例 (前 10 条):\n" +
            "\n".join(failures[:10]))

    def test_sweep_count_sanity(self):
        # 防空转: 扫描集缩水到没有代表性时显式失败
        self.assertGreaterEqual(len(self.FREQS), 2000)


class NumericBoundaryTests(unittest.TestCase):
    """F-103 数值边界缺口三连修: 越界输入必须显式 ERROR, 不得静默截断。

    共同性质: 生成的每个寄存器值都装得进对应寄存器的物理位宽
    (SysTick LOAD 24 位 / BRR 16 位 / CCR 16 位), 且配置域合法
    (PWM ch 1-4 / duty 0-100)。"""

    def test_systick_load_within_24bit(self):
        # 72MHz 全整数分频表扫: 有效输出 LOAD ≤ 0xFFFFFF; 越界频率报错
        for freq in (2, 3, 4, 10, 100, 1000, 8000, 72000, 720000, 7200000):
            with self.subTest(freq=freq):
                out = gen_periph.gen_systick(freq)
                if out.startswith("/* ERROR"):
                    # 报错也合法——但必须真越界 (LOAD > 24 位)
                    self.assertGreater(72_000_000 // freq - 1, 0xFFFFFF)
                    continue
                load = int(re.search(r"SysTick->LOAD = (\d+);", out).group(1))
                self.assertLessEqual(load, 0xFFFFFF)
        # 实测锚点: --freq 2 → 35999999 > 0xFFFFFF (16777215), 必报错
        out = gen_periph.gen_systick(2)
        self.assertTrue(out.startswith("/* ERROR"))
        self.assertIn("24-bit", out)
        # 边界: freq 4 → 17999999 仍越界报错; freq 5 → 14399999 ≤ 0xFFFFFF 有效
        self.assertTrue(gen_periph.gen_systick(4).startswith("/* ERROR"))
        out5 = gen_periph.gen_systick(5)
        self.assertIn("SysTick->LOAD = 14399999;", out5)

    def test_usart_low_baud_brr_overflow_errors(self):
        # mantissa 12 位上限 0xFFF: USART2 最低可表 550 baud; 300 必溢出
        out = gen_periph.gen_usart("USART2", 300, "PA2", "PA3")
        self.assertTrue(out.startswith("/* ERROR"))
        self.assertIn("12-bit", out)
        self.assertNotIn("->BRR =", out)
        # 边界内侧: 600 baud @36MHz → mantissa 3750/16=234 ≤ 0xFFF 有效
        out600 = gen_periph.gen_usart("USART2", 600, "PA2", "PA3")
        self.assertIn("USART2->BRR = 0x", out600)
        # 常用最低档 1200 必须仍然工作 (反向钉: 收紧不误伤)
        self.assertIn("USART2->BRR = 0x",
                      gen_periph.gen_usart("USART2", 1200, "PA2", "PA3"))

    def test_pwm_channel_beyond_4_errors(self):
        # TIM2~4 仅 4 通道; ch=5 旧行为写 CCR5 保留位静默无效
        for ch in (0, 5, 9, -1):
            with self.subTest(ch=ch):
                out = gen_periph.gen_pwm("TIM2", ch, "PA0", 1000, 50)
                self.assertTrue(out.startswith("/* ERROR"))
                self.assertNotIn("->CCR", out)
        self.assertIn("CCR4", gen_periph.gen_pwm("TIM2", 4, "PA3", 1000, 50))

    def test_pwm_duty_and_freq_domain(self):
        for duty in (-1, 101, 250):
            with self.subTest(duty=duty):
                out = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, duty)
                self.assertTrue(out.startswith("/* ERROR"))
        for duty in (0, 100):  # 边界合法值不误伤
            self.assertIn("->CCR1", gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, duty))
        for freq in (0, -1000):
            with self.subTest(freq=freq):
                self.assertTrue(
                    gen_periph.gen_pwm("TIM2", 1, "PA0", freq, 50).startswith("/* ERROR"))

    def test_cli_exits_nonzero_on_all_new_boundaries(self):
        """F-086 的退出码纪律经 _emit 泛化到全部 ERROR 出口"""
        import subprocess
        cases = [
            ["--type", "systick", "--freq", "2"],
            ["--type", "usart", "--usart", "USART2", "--baud", "300"],
            ["--type", "pwm", "--timer", "TIM2", "--ch", "5", "--pin", "PA0"],
            ["--type", "pwm", "--timer", "TIM2", "--ch", "1", "--pin", "PA0",
             "--duty", "150"],
            ["--type", "gpio", "--pin", "PA0", "--mode", "out-pp-99mhz"],  # argparse rc=2
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                r = subprocess.run(
                    [sys.executable, os.path.join(os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "gen_periph.py")] + argv,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=60)
                self.assertNotEqual(r.returncode, 0,
                                    f"{argv} 应失败退出, 实际 rc=0:\n{r.stdout[-300:]}")
                blob = r.stdout + r.stderr
                self.assertTrue("ERROR" in blob or "invalid choice" in blob,
                                f"{argv}: 失败必须带可诊断信息:\n{blob[-300:]}")
        # timer-int 既有 F-086 通道经 _emit 收敛后行为不变 (反向钉)
        r = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))),
                "scripts", "gen_periph.py"),
             "--type", "timer-int", "--timer", "TIM2", "--period-ms", "1000"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("/* ERROR", r.stdout)

    def test_i2c_spi_error_exits_converged_to_emit_f108(self):
        """F-108 (复审 M-2): i2c/spi 三个既有 ERROR 出口曾 print 直出 rc=0
        ——机器消费方按退出码判定会漏。接入 _emit 后与其余生成器同语义。"""
        import subprocess
        for argv in (["--type", "i2c", "--i2c", "I2C9"],
                     ["--type", "i2c", "--i2c", "I2C1", "--speed", "1000000"],
                     ["--type", "spi", "--spi", "SPI9"]):
            with self.subTest(argv=argv):
                r = subprocess.run(
                    [sys.executable, os.path.join(os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "gen_periph.py")] + argv,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=60)
                self.assertEqual(r.returncode, 1,
                                 f"{argv} ERROR 出口应 rc=1:\n{r.stdout[-200:]}")
                self.assertIn("/* ERROR", r.stdout)

    def test_zero_input_structured_error_f108(self):
        """F-108 (L-1): systick/usart/timer-int 零值曾裸 ZeroDivisionError
        traceback (rc=1 但非可诊断 ERROR) → 与 gen_pwm freq 守卫对齐。"""
        cases = [
            (lambda: gen_periph.gen_systick(0), "freq=0"),
            (lambda: gen_periph.gen_systick(-3), "freq=-3"),
            (lambda: gen_periph.gen_usart("USART1", 0, "PA9", "PA10"), "baud=0"),
            (lambda: gen_periph.gen_timer_int("TIM2", 0, 72), "period 0ms"),
        ]
        for fn, needle in cases:
            with self.subTest(needle=needle):
                out = fn()
                self.assertTrue(out.startswith("/* ERROR"),
                                f"应结构化报错, 实际: {out[:80]}")
                self.assertIn(needle, out)



class TimerIntArrBoundaryTests(unittest.TestCase):
    """F-086 缺陷 2 修复钉: timer-int 域纳入扫描 — ARR 16 位边界。

    timer-int 固定 PSC=71 (1MHz tick) ⇒ ARR = 1000*period_ms - 1，
    period_ms ≥ 66 即超 65535 被硬件截断，注释却按未截断值写 (C 类静默)。
    处置路线 (a) 报错退出: 周期类配置无合理近似 (gen_pwm 的"最接近值+
    旁注"依赖候选 ARR 表可缩放，此处 PSC 固定无自由度)，不产出假装
    正确的固件配置。
    """

    def test_representable_periods_arr_exact(self):
        # 真实阈值: target_hz = 1000//period_ms (整除), ARR = 1e6//target_hz - 1
        # → period ≤ 62ms 时 target_hz ≥ 16, ARR ≤ 62499; 63ms 起即溢出
        # (简报 §2 估算"约 66ms"未计入该整除, 以实测为准)
        for period_ms in (1, 10, 50, 62):
            with self.subTest(period_ms=period_ms):
                out = gen_periph.gen_timer_int("TIM2", period_ms, 72)
                arr = int(re.search(r"->ARR = (\d+);", out).group(1))
                self.assertEqual(arr, 1_000_000 // (1000 // period_ms) - 1)
                self.assertLessEqual(arr, 65535)

    def test_unrepresentable_period_returns_error_not_truncation(self):
        for period_ms in (63, 66, 100, 1000):
            with self.subTest(period_ms=period_ms):
                out = gen_periph.gen_timer_int("TIM2", period_ms, 72)
                self.assertTrue(
                    out.startswith("/* ERROR"),
                    f"{period_ms}ms 应显式报错而非产出被截断的 ARR")
                self.assertIn("65535", out)

    def test_cli_exits_nonzero_on_unrepresentable_period(self):
        """简报 §3⑤: CLI 报错路线须退出码非 0 (机器消费方可判失败)"""
        import subprocess
        r = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))),
                "scripts", "gen_periph.py"),
             "--type", "timer-int", "--timer", "TIM2", "--period-ms", "1000"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60)
        self.assertEqual(r.returncode, 1, r.stdout[-300:])
        self.assertIn("/* ERROR", r.stdout)


if __name__ == "__main__":
    unittest.main()
