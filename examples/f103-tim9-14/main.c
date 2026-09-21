/* f103-tim9-14 — T2 手写寄存器级样例 (编译级)。
 * 用途: TIM9 (双通道) 与 TIM10 (单通道) PWM 配置实做; TIM11~14 为同构
 *       变体, 实例差异 (基址/总线/使能位) 见 README 表。
 * ref.json anchor: peripherals.TIM9/TIM10 (寄存器布局), RCC.APB2ENR
 *                  bits 19/20/21=TIM9EN/TIM10EN/TIM11EN, RCC.APB1ENR
 *                  bits 6/7/8=TIM12EN/TIM13EN/TIM14EN。
 * GAP-D-5 (已修正 @F-179): ref.json 外设条目的 bus 字段曾与其 RCC 使能位
 *          归属矛盾 (TIM9 记 APB1, TIM12/13/14 记 APB2) — F-179 已按 RCC
 *          位数据修正为 TIM9=APB2、TIM12/13/14=APB1; 类级防线见
 *          tests/test_ref_bus_crosscheck.py。本样例行为不受影响（原即依
 *          RCC 位数据）。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): 新增 host mock — 双实例序列位型 + 分频
 *          换算已知答案。
 */
#include "f103_regs.h"

static void tim9_dual_pwm_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_TIM9EN;   /* ref.json RCC.APB2ENR bit19 */
    __DSB();
    TIM9->PSC  = 71;                      /* 1MHz */
    TIM9->ARR  = 999;                     /* 1kHz */
    TIM9->CCR1 = 250;                     /* CH1 25% */
    TIM9->CCR2 = 750;                     /* CH2 75% */
    /* CCMR1_Output (ref.json TIM9.CCMR1_Output): OC1M@4:6, OC1PE@3,
     * OC2M@12:14, OC2PE@11 */
    TIM9->CCMR1 = (6UL << 4) | (1UL << 3) | (6UL << 12) | (1UL << 11);
    TIM9->CCER  = (1UL << 0) | (1UL << 4);/* CC1E + CC2E (ref.json TIM9.CCER) */
    TIM9->CR1   = (1UL << 7) | (1UL << 0);
}

static void tim10_pwm_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_TIM10EN;  /* ref.json RCC.APB2ENR bit20 */
    __DSB();
    TIM10->PSC  = 71;
    TIM10->ARR  = 499;                    /* 2kHz */
    TIM10->CCR1 = 250;
    /* TIM10 单通道: CCMR1_Output 仅 OC1 域 (ref.json TIM10.CCMR1_Output
     * bits 4:6=OC1M 3=OC1PE 0:1=CC1S) */
    TIM10->CCMR1 = (6UL << 4) | (1UL << 3);
    TIM10->CCER  = (1UL << 0);
    TIM10->CR1   = (1UL << 7) | (1UL << 0);
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    tim9_dual_pwm_init();
    tim10_pwm_init();
    for (;;) {
        __WFI();
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

/* 推导辅助 (host-only): f = clk/((PSC+1)*(ARR+1)) — 期望常数均为手算;
 * 16 位宽度防御与 tim5 家族同口径 */
static uint32_t tim_output_hz(uint32_t tim_clk_hz, uint32_t psc,
                              uint32_t arr)
{
    uint32_t div;
    if (psc > 0xFFFFu || arr > 0xFFFFu) {
        return 0u;
    }
    div = (psc + 1u) * (arr + 1u);
    return div == 0u ? 0u : tim_clk_hz / div;
}

int main(void)
{
    /* 组1 TIM9 双通道序列位型 (逐项手算):
     * CCMR1 = OC1M=110(4:6)|OC1PE(3)|OC2M=110(12:14)|OC2PE(11)
     *       = 0x60|0x08|0x6000|0x800 = 0x6868;
     * CCER = CC1E(0)|CC2E(4) = 0x11; CR1 = ARPE(7)|CEN(0) = 0x81 */
    tim9_dual_pwm_init();
    CHECK(f103_mock_RCC.APB2ENR & RCC_APB2ENR_TIM9EN);
    CHECK(f103_mock_TIM9.PSC == 71u && f103_mock_TIM9.ARR == 999u);
    CHECK(f103_mock_TIM9.CCR1 == 250u && f103_mock_TIM9.CCR2 == 750u);
    CHECK(f103_mock_TIM9.CCMR1 == 0x6868u);
    CHECK(f103_mock_TIM9.CCER == 0x11u);
    CHECK(f103_mock_TIM9.CR1 == 0x81u);
    /* 组2 TIM10 单通道序列位型: CCMR1=0x68 (仅 OC1 域), CCER=CC1E */
    tim10_pwm_init();
    CHECK(f103_mock_RCC.APB2ENR & RCC_APB2ENR_TIM10EN);
    CHECK(f103_mock_TIM10.PSC == 71u && f103_mock_TIM10.ARR == 499u);
    CHECK(f103_mock_TIM10.CCR1 == 250u);
    CHECK(f103_mock_TIM10.CCMR1 == 0x68u);
    CHECK(f103_mock_TIM10.CCER == 1u);
    CHECK(f103_mock_TIM10.CR1 == 0x81u);
    /* 组3 分频已知答案 (手算): TIM9 72M/(72*1000)=1kHz;
     * TIM10 72M/(72*500)=2kHz */
    CHECK(tim_output_hz(72000000u, 71u, 999u) == 1000u);
    CHECK(tim_output_hz(72000000u, 71u, 499u) == 2000u);
    /* 组4 双实例互不串扰 (mock 终态再确认) */
    CHECK(f103_mock_TIM9.ARR == 999u && f103_mock_TIM10.ARR == 499u);
    /* 组5 边界+防御: PSC=0 + ARR 满档 → 1098; PSC 超宽 → 0 哨兵 */
    CHECK(tim_output_hz(72000000u, 0u, 0xFFFFu) == 1098u);
    CHECK(tim_output_hz(72000000u, 0x10000u, 0u) == 0u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
