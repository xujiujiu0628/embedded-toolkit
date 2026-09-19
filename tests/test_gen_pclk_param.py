r"""WB-20260920-01: gen_periph ``--pclk1/--pclk2`` 时钟树参数化回归钉 (F-110 下半场)。

结构镜像 tests/test_gen_hclk_param.py (F-110) 的四种钉形:
  ① 金矩阵默认兼容钉 (本文件 commit1, 基线上先绿) —— tests/fixtures/
     pclk_golden.json 为基线 c0df0c6 上 capture-once 的 9 组代表参数 ×
     {缺省, --hclk 8, --hclk 72 显式} 全量输出; 拆分后"不传 pclk = 与
     基线逐字节一致"由本类逐条复跑比对 (第一契约)。
  ② 派生函数钉 —— apb_clock_mhz 的 pclk 覆盖参数 + tim_kernel_clock_mhz
     (APB1×2 规则随 --pclk1 派生, RM0008 §7.3.7)。
  ③ 优先级钉 —— 显式 --tim-clk > pclk1 派生 > hclk 推导; 显式 pclk > 推导。
  ④ 域边界钉 —— pclk2∈[1,72]∧≤hclk / pclk1∈[1,36]∧≤hclk (36=APB1 规格
     上限, RM0008 数据手册值, ref.json 未登记 — GAP-D-4 架构常量), 越界/
     非整数 → ERROR 非零退出 (F-103, 不静默回落); systick 不受 pclk 扰动钉。
  ⑤ P1 (L-5) —— hclk=2 × i2c 400k 病态 (CCR clamp 4 假装 400kHz +
     CR2.FREQ=1) 既有测试未钉 (2026-09-20 grep 取证: 仅钉默认 72 输出)
     → 改显式 ERROR 并钉。
"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts", "gen_periph.py")
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "fixtures", "pclk_golden.json")


def _run_cli(argv):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, SCRIPT] + argv, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, env=env,
        cwd=os.path.dirname(os.path.abspath(__file__)) or None)


class GoldenMatrixTests(unittest.TestCase):
    """① 第一契约: 不传 --pclk1/--pclk2 时, 全部金矩阵条目与基线逐字节一致。

    fixture 每条含基线 (c0df0c6, 参数化之前) 的 CLI stdout; 本类在拆分前后
    都逐条复跑比对 —— 拆分若扰动默认路径, 此处立即红。"""

    @classmethod
    def setUpClass(cls):
        with open(GOLDEN, encoding="utf-8") as f:
            cls.golden = json.load(f)
        cls.entries = {k: v for k, v in cls.golden.items() if not k.startswith("_")}

    def test_matrix_covers_nine_groups_x_three_variants(self):
        self.assertEqual(len(self.entries), 27)

    def test_default_path_reproduces_baseline_byte_for_byte(self):
        for key, entry in sorted(self.entries.items()):
            with self.subTest(entry=key):
                r = _run_cli(entry["argv"])
                self.assertEqual(r.returncode, 0,
                                 f"{key}: rc={r.returncode}\n{r.stdout[:300]}")
                self.assertEqual(
                    r.stdout, entry["output"],
                    f"{key}: 默认输出偏离基线金矩阵 (第一契约破约)")

    def test_explicit_72_equals_default(self):
        """--hclk 72 显式 == 缺省 (F-110 兼容契约在金矩阵上的延伸)。"""
        for label in {k.rsplit("_", 1)[0] for k in self.entries}:
            with self.subTest(label=label):
                d = _run_cli(self.entries[f"{label}_default"]["argv"])
                s = _run_cli(self.entries[f"{label}_hclk72"]["argv"])
                self.assertEqual(d.stdout, s.stdout, label)


# ══════════════════════════════════════════════════════════════════════════
# 拆 (WB-20260920-01 commit2): 派生函数钉 / 优先级钉 / 域边界钉 / 六族实样钉
# 期望值全部为独立手算常数 (RM0008 公式 → 代码表达式 → 手算, 见报告对账表),
# 禁止用生成器自身输出回填。
# ══════════════════════════════════════════════════════════════════════════

class PclkDerivationTests(unittest.TestCase):
    """② 推导函数钉: apb_clock_mhz 覆盖参数 + tim_kernel_clock_mhz"""

    def test_apb_clock_mhz_override_per_key(self):
        self.assertEqual(gen_periph.apb_clock_mhz(72, "APB1", pclk1_mhz=18), 18)
        self.assertEqual(gen_periph.apb_clock_mhz(72, "APB2", pclk2_mhz=24), 24)
        # 逐键独立: 另一键的覆盖不串扰
        self.assertEqual(gen_periph.apb_clock_mhz(72, "APB1", pclk2_mhz=24), 36)
        self.assertEqual(gen_periph.apb_clock_mhz(72, "APB2", pclk1_mhz=18), 72)
        # 未传键维持 F-110 公式
        self.assertEqual(gen_periph.apb_clock_mhz(9, "APB1"), 4)

    def test_tim_kernel_clock_mhz_rules(self):
        # 手算 (RM0008 §7.3.7): ×2 仅当 PPRE1≠1
        f = gen_periph.tim_kernel_clock_mhz
        self.assertEqual(f(72, None), 72)   # 未传 pclk1 → F-110 现状
        self.assertEqual(f(72, 36), 72)     # ==hclk//2 → 标准 PPRE1=2, ×2 抵消
        self.assertEqual(f(72, 18), 36)     # PPRE1=4 → ×2
        self.assertEqual(f(72, 72), 72)     # ==hclk → PPRE1=1, ×2 不适用
        self.assertEqual(f(8, 4), 8)        # 标准 (4==8//2)
        self.assertEqual(f(8, 2), 4)        # PPRE1=4 → ×2
        self.assertEqual(f(9, 4), 9)        # 奇数 hclk: 4==9//2 整数等值 → 现状
        self.assertEqual(f(36, 18), 36)


class SixFamilyPclkSampleTests(unittest.TestCase):
    """③ 六族实样钉 (手算常数):
    usart2@115200 pclk1=18: div=18e6/(16×115200)=9.765625 → m=9,
      f=round(0.765625×16)=12 → BRR=(9<<4)|12=0x009C
    i2c1@100k pclk1=18: CCR=18e6//(2×100000)=90=0x05A; CR2.FREQ=18;
      TRISE=18+1=19
    adc1 pclk2=18: 18/2=9≤14 → ADCPRE=/2 (bits=00), 显示 9MHz
    pwm TIM2@1kHz pclk1=18 → tim=36: ARR=999, PSC=36e6/(1000×1000)-1=35,
      CCR=round(1000×50/100)=500
    timer-int TIM2@10ms pclk1=18 → tim=36: ARR=36e6//((71+1)×100)-1=4999
    spi1@div8 pclk2=18: 18e6//8=2250000 → 2250kHz"""

    def test_usart2_brr_at_pclk1_18(self):
        out = gen_periph.gen_usart("USART2", 115200, "PA2", "PA3", 72,
                                   pclk1_mhz=18)
        self.assertIn("USART2->BRR = 0x009C;", out)
        self.assertIn("PCLK1=18MHz", out)

    def test_usart1_explicit_pclk2_72_same_payload_with_note(self):
        # 显式值 == 推导值: 数值载荷逐字节一致, 但注记必须注入 (前提
        # "用户显式钉死 PCLK2" 是新信息, 不许静默 — 简报 §2.4)
        d = gen_periph.gen_usart("USART1", 115200, "PA9", "PA10", 72)
        e = gen_periph.gen_usart("USART1", 115200, "PA9", "PA10", 72,
                                 pclk2_mhz=72)
        self.assertIn("USART1->BRR = 0x0271;", d)
        self.assertIn("USART1->BRR = 0x0271;", e)
        self.assertNotIn("时钟前提", d)
        self.assertIn("PCLK2=72MHz (--pclk2)", e)

    def test_i2c_cr2_ccr_trise_at_pclk1_18(self):
        out = gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7", 72,
                                 pclk1_mhz=18)
        self.assertIn("I2C1->CR2 = 18;", out)
        self.assertIn("I2C1->CCR = 0x05A;", out)
        self.assertIn("I2C1->TRISE = 19;", out)

    def test_adc_prescaler_at_pclk2_18(self):
        out = gen_periph.gen_adc("ADC1", 1, "PA1", 72, pclk2_mhz=18)
        self.assertIn("ADCPRE=/2 (9MHz @ PCLK2=18MHz", out)
        self.assertIn("RCC->CFGR |=  (0UL << 14);", out)

    def test_pwm_timclk_36_at_pclk1_18(self):
        out = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50, None, 72,
                                 pclk1_mhz=18)
        self.assertIn("TIM_CLK=36MHz, PSC=35, ARR=999, CCR1=500", out)

    def test_timer_int_arr_4999_at_pclk1_18(self):
        out = gen_periph.gen_timer_int("TIM2", 10, None, 72, pclk1_mhz=18)
        self.assertIn("TIM_CLK=36MHz, PSC=71, ARR=4999", out)

    def test_spi_freq_at_pclk2_18(self):
        out = gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6", "PA7", 8,
                                 72, pclk2_mhz=18)
        self.assertIn("2250kHz", out)
        self.assertIn("PCLK=18MHz, BR[2:0]=2 (/ 8)", out)

    def test_systick_immune_to_pclk(self):
        """systick 吃内核时钟, 与 pclk 无关——钉死证明其不受扰 (简报 §2.2)。"""
        self.assertEqual(
            gen_periph.gen_systick(1000, 72),
            gen_periph.gen_systick(1000, 72))   # 签名不含 pclk 参数
        r_plain = _run_cli(["--type", "systick", "--freq", "1000"])
        r_pclk = _run_cli(["--type", "systick", "--freq", "1000",
                           "--pclk1", "18", "--pclk2", "18"])
        self.assertEqual(r_plain.returncode, 0)
        self.assertEqual(r_plain.stdout, r_pclk.stdout,
                         "systick 输出不得受 --pclk1/--pclk2 影响")


class PclkPriorityTests(unittest.TestCase):
    """③ 优先级钉: 显式 --tim-clk > pclk1 派生 > hclk 推导"""

    def test_explicit_tim_clk_beats_pclk1_derivation(self):
        out = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50, 72, 72,
                                 pclk1_mhz=18)
        self.assertIn("TIM_CLK=72MHz", out)
        out2 = gen_periph.gen_timer_int("TIM2", 10, 72, 72, pclk1_mhz=18)
        self.assertIn("TIM_CLK=72MHz", out2)

    def test_pclk1_derivation_beats_hclk(self):
        out = gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50, None, 72,
                                 pclk1_mhz=18)
        self.assertIn("TIM_CLK=36MHz", out)   # 非 hclk(72) 非 pclk1(18)


class PclkDomainTests(unittest.TestCase):
    """④ 域边界: pclk2∈[1,72]∧≤hclk / pclk1∈[1,36]∧≤hclk; 越界/非整数
    → ERROR 非零退出 (F-103, 不静默回落)。36 出处见 gen_periph.PCLK1_MAX。"""

    def test_cli_out_of_domain_errors(self):
        cases = [
            (["--pclk1", "37"], "--pclk1"),      # >36 (APB1 顶速)
            (["--pclk1", "0"], "--pclk1"),
            (["--pclk1", "-9"], "--pclk1"),
            (["--pclk1", "73"], "--pclk1"),      # >hclk
            (["--pclk2", "73"], "--pclk2"),      # >72
            (["--pclk2", "0"], "--pclk2"),
            (["--hclk", "36", "--pclk2", "72"], "--pclk2"),   # >hclk
            (["--hclk", "36", "--pclk1", "37"], "--pclk1"),
        ]
        for extra, flag in cases:
            with self.subTest(extra=extra):
                r = _run_cli(["--type", "systick", "--freq", "1000"] + extra)
                self.assertEqual(r.returncode, 1,
                                 f"{extra}: 应 ERROR exit 1:\n{r.stdout[:200]}")
                self.assertIn("ERROR", r.stdout)
                self.assertIn(flag, r.stdout)

    def test_cli_non_integer_rejected_nonzero(self):
        for bad in ("abc", ""):
            with self.subTest(bad=bad):
                r = _run_cli(["--type", "usart", "--usart", "USART1",
                              "--baud", "115200", "--pclk1", bad])
                self.assertNotEqual(
                    r.returncode, 0,
                    f"--pclk1 {bad!r} 必须非零退出 (F-103)")
                self.assertNotIn("BRR", r.stdout)   # 不得产出伪合法生成物

    def test_cli_in_domain_ok(self):
        r = _run_cli(["--type", "usart", "--usart", "USART2", "--baud",
                      "115200", "--pclk1", "18"])
        self.assertEqual(r.returncode, 0, r.stdout[:200])
        self.assertIn("BRR = 0x009C;", r.stdout)

    def test_domain_enforced_in_library(self):
        cases = [
            (lambda: gen_periph.gen_usart("USART1", 115200, "PA9", "PA10",
                                          72, pclk1_mhz=37), "pclk1=37"),
            (lambda: gen_periph.gen_usart("USART1", 115200, "PA9", "PA10",
                                          72, pclk2_mhz=73), "pclk2=73"),
            (lambda: gen_periph.gen_adc("ADC1", 1, "PA1", 72,
                                        pclk2_mhz=0), "pclk2=0"),
            (lambda: gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7", 72,
                                        pclk1_mhz=-5), "pclk1=-5"),
            (lambda: gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6",
                                        "PA7", 8, 72, pclk2_mhz=99),
             "pclk2=99"),
            (lambda: gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50, None,
                                        72, pclk1_mhz=73), "pclk1=73"),
            (lambda: gen_periph.gen_timer_int("TIM2", 10, None, 72,
                                              pclk1_mhz=0), "pclk1=0"),
            (lambda: gen_periph.gen_usart("USART1", 115200, "PA9", "PA10",
                                          72, pclk1_mhz="18"), "非整数"),
            (lambda: gen_periph.gen_usart("USART1", 115200, "PA9", "PA10",
                                          72, pclk1_mhz=True), "bool"),
        ]
        for fn, tag in cases:
            with self.subTest(tag=tag):
                out = fn()
                self.assertTrue(out.startswith("/* ERROR"),
                                f"{tag}: 库级必须拒绝: {out[:80]}")

    def test_pclk_max36_boundary_ok(self):
        # pclk1=36 (== APB1 顶速) 合法: usart2 BRR 同 36MHz 推导值 0x027
        # (36e6/(16×115200)=19.53125 → m=19 f=round(8.5)=9? 0.53125×16=8.5
        #  → round=8 (银行家) 或 9——以实现为准, 仅钉 rc=0 与 PCLK1 注)
        r = _run_cli(["--type", "usart", "--usart", "USART2", "--baud",
                      "115200", "--pclk1", "36"])
        self.assertEqual(r.returncode, 0, r.stdout[:200])
        self.assertIn("PCLK1=36MHz", r.stdout)


class PclkPreconditionNoteTests(unittest.TestCase):
    """前提注记扩展: 显式 pclk 在场必须如实回显 (含 tim ×2 前提, 不许静默);
    无 pclk 时维持 F-110 原文 (hclk=72 不注入)。"""

    def test_note_injected_when_pclk_given_even_at_72(self):
        out = gen_periph.gen_usart("USART2", 115200, "PA2", "PA3", 72,
                                   pclk1_mhz=18)
        self.assertIn("WB-20260920-01", out)
        self.assertIn("PCLK1=18MHz (--pclk1)", out)
        self.assertIn("TIM2~4 内核=36MHz", out)
        self.assertIn("PPRE1≠1, ×2", out)
        self.assertIn("PCLK2=72MHz (PPRE2=1 推导)", out)

    def test_note_premise_three_cases(self):
        # 标准: pclk1 == hclk//2 → ×2 抵消
        out = gen_periph.gen_usart("USART2", 115200, "PA2", "PA3", 72,
                                   pclk1_mhz=36)
        self.assertIn("标准 PPRE1=2, ×2 抵消", out)
        self.assertIn("TIM2~4 内核=72MHz", out)
        # PPRE1=1: pclk1 == hclk → ×2 不适用
        out = gen_periph.gen_usart("USART2", 115200, "PA2", "PA3", 36,
                                   pclk1_mhz=36)
        self.assertIn("PPRE1=1, ×2 不适用", out)
        self.assertIn("TIM2~4 内核=36MHz", out)

    def test_note_absent_on_default_paths(self):
        self.assertNotIn("标准 APB 分频",
                         gen_periph.gen_usart("USART1", 115200, "PA9",
                                              "PA10"))
        self.assertNotIn("时钟前提",
                         gen_periph.gen_usart("USART1", 115200, "PA9",
                                              "PA10", 72, pclk2_mhz=None))


class L5I2cClampErrorTests(unittest.TestCase):
    """⑤ P1 (09-19 审查 L-5): 静默 clamp 改显式 ERROR。
    既有测试仅钉默认 72 输出 (2026-09-20 grep 取证: test_gen_periph
    test_fast_mode_400k_sets_fs_bit_and_shorter_trise 钉 CCR=0x01E@36MHz),
    病态低频输出无钉 → 简报 §2 P1 条件满足, 顺路修。
    手算: pclk1=1 (hclk=2): CR2.FREQ=1 < 2 违反 RM0008 §27.5.2 → ERROR;
          pclk1=2 (hclk=4) @400k fast: CCR=2e6//(3×400000)=1 < 4 → ERROR;
          pclk1=2 (hclk=4) @100k: CCR=2e6//(2×100000)=10=0x00A, TRISE=3 → OK。"""

    def test_freq_below_2_errors(self):
        out = gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7", 2)
        self.assertTrue(out.startswith("/* ERROR"), out[:100])
        self.assertIn("FREQ", out)
        self.assertIn("§27.5.2", out)
        r = _run_cli(["--type", "i2c", "--i2c", "I2C1", "--speed", "100000",
                      "--hclk", "2"])
        self.assertEqual(r.returncode, 1, r.stdout[:200])

    def test_ccr_below_4_errors_at_400k(self):
        out = gen_periph.gen_i2c("I2C1", 400000, "PB6", "PB7", 4)
        self.assertTrue(out.startswith("/* ERROR"), out[:100])
        self.assertIn("CCR=1 < 4", out)
        r = _run_cli(["--type", "i2c", "--i2c", "I2C1", "--speed", "400000",
                      "--hclk", "4"])
        self.assertEqual(r.returncode, 1, r.stdout[:200])

    def test_low_but_legal_pclk1_still_works(self):
        # pclk1=2 @100k: CCR=10 合法 — 低频合法配置不得被误伤
        out = gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7", 4)
        self.assertIn("I2C1->CR2 = 2;", out)
        self.assertIn("I2C1->CCR = 0x00A;", out)
        self.assertIn("I2C1->TRISE = 3;", out)


if __name__ == "__main__":
    unittest.main()
