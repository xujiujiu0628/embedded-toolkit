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


if __name__ == "__main__":
    unittest.main()
