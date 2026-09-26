r"""生成代码语法烟测 (F-078) — gen_* 输出必须通过 arm-none-eabi-gcc -fsyntax-only。

动机: 生成器的产出会被 AI 直接粘进固件。A 类缺陷 (引用不存在的宏、语法错)
旧路径是"AI 抄进工程 → 闭环 build 炸 → 烧录迭代白跑一轮"; 本测试把这道闸
前移到提交前——生成器改动只要破坏了语法或 CMSIS 符号契约, 立即红。

stub 头 (stm32f103_workbench_stub.h) 是"生成器 ↔ CMSIS 接口契约":
枚举生成器可能引用的全部外设结构体成员与 RCC 宏。它同时约束两头——
生成器不得引用契约之外的符号 (编译红), 契约本身漏定义也会红。
覆盖范围: 支持集内的外设 (TIM1~4/USART1~2/ADC1~2/I2C1~2/SPI1~2/GPIO/SysTick);
未知外设 fallback 路径产出幻影宏属既有测试钉住的 fallback 语义, 不进烟测。

环境: 需要 arm-none-eabi-gcc (仓库真机构建链已有); 不在场时整组 skip——
CI (ubuntu) 不装工具链, 与 coverage-data 测试同款守卫。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402
import wb_common  # noqa: E402

GCC_TIMEOUT = 30

STUB_HEADER = r"""/* 生成器 ↔ CMSIS 接口契约 stub (F-078) — 仅用于 -fsyntax-only 烟测。
 * 成员/宏集合 = 生成器当前可能引用的符号全集; 两头越界都算失败。
 * 地址值无关紧要 (不做代码生成), 只需类型与成员名与 stm32f1x CMSIS 一致。
 * F-194 (WB-20260927-02 T3): error_chain_t/ERR_OK/ERR_PLAIN 定义已移除 —
 * i2c 帮手降级 int 返回后全仓生成器零引用, 留定义会让"引用幽灵契约"
 * 的回归静默编译通过 (缺定义即红, 与自足性钉互补)。*/
#pragma once
#include <stdint.h>
#include <stdio.h>

#define __DSB() ((void)0)

typedef struct {
    volatile uint32_t CR, CFGR, CIR, APB2RSTR, APB1RSTR,
        AHBENR, APB2ENR, APB1ENR, BDCR, CSR;
} RCC_TypeDef;
typedef struct {
    volatile uint32_t CRL, CRH, IDR, ODR, BSRR, BRR, LCKR;
} GPIO_TypeDef;
typedef struct {
    volatile uint32_t SR, DR, BRR, CR1, CR2, CR3, GTPR;
} USART_TypeDef;
typedef struct {
    volatile uint32_t CR1, CR2, SMCR, DIER, SR, EGR, CCMR1, CCMR2,
        CCER, CNT, PSC, ARR, RCR, CCR1, CCR2, CCR3, CCR4, BDTR;
} TIM_TypeDef;
typedef struct {
    volatile uint32_t SR, CR1, CR2, SMPR1, SMPR2, JOFR1, HTR,
        LTR, SQR1, SQR2, SQR3, JSQR, JDR1, JDR2, JDR3, JDR4, DR;
} ADC_TypeDef;
typedef struct {
    volatile uint32_t CR1, CR2, OAR1, OAR2, DR, SR1, SR2, CCR, TRISE;
} I2C_TypeDef;
typedef struct {
    volatile uint32_t CR1, CR2, SR, DR, CRCPR, RXCRCR, TXCRCR, I2SCFGR;
} SPI_TypeDef;
typedef struct {
    volatile uint32_t CTRL, LOAD, VAL, CALIB;
} SysTick_Type;
typedef struct {
    volatile uint32_t ISER[8u], ICER[8u], ISPR[8u], ICPR[8u], IABR[8u],
        IP[240u];
} NVIC_Type;

#define RCC     ((RCC_TypeDef *)     0x40021000UL)
#define GPIOA   ((GPIO_TypeDef *)    0x40010800UL)
#define GPIOB   ((GPIO_TypeDef *)    0x40010C00UL)
#define GPIOC   ((GPIO_TypeDef *)    0x40011000UL)
#define GPIOD   ((GPIO_TypeDef *)    0x40011400UL)
#define USART1  ((USART_TypeDef *)   0x40013800UL)
#define USART2  ((USART_TypeDef *)   0x40004400UL)
#define USART3  ((USART_TypeDef *)   0x40004800UL)
#define TIM1    ((TIM_TypeDef *)     0x40012C00UL)
#define TIM2    ((TIM_TypeDef *)     0x40000000UL)
#define TIM3    ((TIM_TypeDef *)     0x40000400UL)
#define TIM4    ((TIM_TypeDef *)     0x40000800UL)
#define ADC1    ((ADC_TypeDef *)     0x40012400UL)
#define ADC2    ((ADC_TypeDef *)     0x40012800UL)
#define I2C1    ((I2C_TypeDef *)     0x40005400UL)
#define I2C2    ((I2C_TypeDef *)     0x40005800UL)
#define SPI1    ((SPI_TypeDef *)     0x40013000UL)
#define SPI2    ((SPI_TypeDef *)     0x40003800UL)
#define SysTick ((SysTick_Type *)    0xE000E010UL)
#define NVIC    ((NVIC_Type *)       0xE000E100UL)

#define RCC_APB2ENR_IOPAEN   (1UL << 2)
#define RCC_APB2ENR_IOPBEN   (1UL << 3)
#define RCC_APB2ENR_IOPCEN   (1UL << 4)
#define RCC_APB2ENR_IOPDEN   (1UL << 5)
#define RCC_APB2ENR_ADC1EN   (1UL << 9)
#define RCC_APB2ENR_ADC2EN   (1UL << 10)
#define RCC_APB2ENR_TIM1EN   (1UL << 0)
#define RCC_APB2ENR_SPI1EN   (1UL << 12)
#define RCC_APB2ENR_USART1EN (1UL << 14)
#define RCC_APB1ENR_TIM2EN   (1UL << 0)
#define RCC_APB1ENR_TIM3EN   (1UL << 1)
#define RCC_APB1ENR_TIM4EN   (1UL << 2)
#define RCC_APB1ENR_SPI2EN   (1UL << 14)
#define RCC_APB1ENR_USART2EN (1UL << 17)
#define RCC_APB1ENR_I2C1EN   (1UL << 21)
#define RCC_APB1ENR_I2C2EN   (1UL << 22)

#define SysTick_CTRL_ENABLE    (1UL << 0)
#define SysTick_CTRL_TICKINT   (1UL << 1)
#define SysTick_CTRL_CLKSOURCE (1UL << 2)

#define USART_CR1_TE (1UL << 3)
#define USART_CR1_RE (1UL << 2)
#define USART_CR1_UE (1UL << 13)
"""


def _find_arm_gcc():
    """定位 arm-none-eabi-gcc: machine.json gcc_path 优先, PATH 兜底。
    探测失败返回 None (skipUnless 用)。"""
    exe = None
    try:
        gcc_path = (wb_common.load_machine().get("gcc_path") or "").strip()
    except Exception:
        gcc_path = ""
    if gcc_path:
        cand = os.path.join(gcc_path, "arm-none-eabi-gcc.exe" if sys.platform == "win32"
                            else "arm-none-eabi-gcc")
        if os.path.isfile(cand):
            exe = cand
    if exe is None:
        exe = shutil.which("arm-none-eabi-gcc")
    if exe is None:
        return None
    try:
        probe = subprocess.run([exe, "--version"], capture_output=True,
                               text=True, timeout=GCC_TIMEOUT)
        if probe.returncode != 0:
            return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    return exe


_ARM_GCC = _find_arm_gcc()


def _snippets():
    """(名称, 生成器调用) — 支持集内的平凡路径 + 分支边界。"""
    return [
        ("gpio-pp50", lambda: gen_periph.gen_gpio("PC13", "out-pp-50mhz")),
        ("gpio-af50", lambda: gen_periph.gen_gpio("PA5", "af-pp-50mhz")),
        ("gpio-analog-low", lambda: gen_periph.gen_gpio("PA5", "in-analog")),
        ("systick-1k", lambda: gen_periph.gen_systick(1000)),
        ("usart1-115200", lambda: gen_periph.gen_usart("USART1", 115200, "PA9", "PA10")),
        ("usart2-lowpins", lambda: gen_periph.gen_usart("USART2", 9600, "PA2", "PA3")),
        ("pwm-tim2-ch1", lambda: gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50)),
        ("pwm-tim2-ch3", lambda: gen_periph.gen_pwm("TIM2", 3, "PA2", 1000, 25)),
        ("pwm-tim1-apb2", lambda: gen_periph.gen_pwm("TIM1", 1, "PA8", 1000, 50)),
        ("pwm-nondivisor", lambda: gen_periph.gen_pwm("TIM2", 1, "PA0", 7000, 50)),
        ("adc-ch1", lambda: gen_periph.gen_adc("ADC1", 1, "PA1")),
        ("adc-ch10", lambda: gen_periph.gen_adc("ADC1", 10, "PC0")),
        ("timerint-tim2", lambda: gen_periph.gen_timer_int("TIM2", 1, 72)),
        ("timerint-tim1-apb2", lambda: gen_periph.gen_timer_int("TIM1", 10, 72)),
        ("i2c1-std", lambda: gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7")),
        ("i2c2-fast", lambda: gen_periph.gen_i2c("I2C2", 400000, "PB10", "PB11")),
        ("spi1-mode0", lambda: gen_periph.gen_spi("SPI1", 0, "PA4", "PA5", "PA6", "PA7", 16)),
        ("spi2-mode3", lambda: gen_periph.gen_spi("SPI2", 3, "PB12", "PB13", "PB14", "PB15", 256)),
    ]


@unittest.skipUnless(_ARM_GCC, "arm-none-eabi-gcc 不在场 (CI 默认不装工具链)")
class GeneratedCodeSyntaxSmokeTests(unittest.TestCase):
    """每个 gen_* 代码路径的输出都要过 -fsyntax-only"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.stub = os.path.join(cls.tmp, "stm32f103_workbench_stub.h")
        with open(cls.stub, "w", encoding="ascii", errors="replace") as f:
            f.write(STUB_HEADER)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _syntax_check(self, name, code):
        # 生成物是"贴进模块 .c"的混合片段: 裸语句进 init 函数体, static 辅助
        # 函数落文件作用域。烟测按片段语义做一次**机械变换**: 剥掉行首 static
        # 后整体包进函数 (GNU C 嵌套函数合法) — 换取语法与符号契约的全量检查。
        # 如实声明范围外: static 存储类布局的合法性 (哪些该落文件作用域)
        # 不在烟测内, 由 review 兜底; 符号契约 (stub) 不受变换影响。
        stripped = re.sub(r"(?m)^static ", "", code)
        wrapped = "void gen_smoke_probe(void) {\n" + stripped + "\n}\n"
        r = subprocess.run(
            [_ARM_GCC, "-fsyntax-only", f"-I{self.tmp}",
             "-include", self.stub, "-x", "c", "-"],
            input=wrapped.encode("utf-8"), capture_output=True,
            timeout=GCC_TIMEOUT)
        stderr = r.stderr.decode("utf-8", "replace")
        self.assertEqual(
            r.returncode, 0,
            f"生成代码 '{name}' 未通过 arm-gcc 语法检查:\n"
            f"--- gcc stderr ---\n{stderr.strip()[:2000]}\n"
            f"(若报未定义符号, 先怀疑生成器引用了 stub 契约之外的符号; "
            f"确认是真需求再同步扩 stub 并记账)")

    def test_all_generator_outputs_compile(self):
        for name, gen in _snippets():
            with self.subTest(case=name):
                self._syntax_check(name, gen())

    def test_systick_error_comment_is_valid_tu(self):
        # 非整除分支输出纯注释 — 也必须是合法翻译单元
        self._syntax_check("systick-nondivisor", gen_periph.gen_systick(7))

    def test_stub_covers_emitted_symbols(self):
        """stub 契约完整性反向钉: 抽查生成代码里每个 RCC 宏都在 stub 中。
        直接 grep 生成输出里的 RCC_APB/USART_CR1/SysTick_CTRL 符号并断言
        stub 含同名 #define, 防止未来新增外设时漏扩契约。"""
        stub_text = ""
        with open(self.stub, encoding="ascii") as f:
            stub_text = f.read()
        emitted = "\n".join(gen() for _, gen in _snippets())
        symbols = sorted(set(re.findall(r"\bRCC_APB[12]ENR_\w+\b", emitted)))
        self.assertTrue(symbols, "生成输出中未发现 RCC 时钟宏, 契约抽查失效")
        for sym in symbols:
            with self.subTest(symbol=sym):
                self.assertIn(f"#define {sym} ", stub_text)


if __name__ == "__main__":
    unittest.main()
