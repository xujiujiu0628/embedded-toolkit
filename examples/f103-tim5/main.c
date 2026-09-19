/* f103-tim5 — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: 通用定时器 PWM 配置序列 (与 TIM2/3/4 同构) + 纯函数
 *       timer_output_hz 供 host 断言分频换算。
 * ref.json anchor: peripherals.TIM5 (base=0x40000C00, 寄存器布局同通用
 *                  定时器), RCC.APB1ENR bit3=TIM5EN。available_on_c8=false。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): host 断言加深 — 16 位宽度边界 + 除零/
 *          ARR 溢出防御 (GAP-G-2 样例侧哨兵)。
 */
#include "f103_regs.h"

/* 输出频率换算 (纯函数, host 可测):
 * f = tim_clk / ((PSC+1) * (ARR+1)) ; ARR 由目标频率反解 */
static uint32_t timer_output_hz(uint32_t tim_clk_hz, uint32_t psc,
                                uint32_t arr)
{
    uint32_t div;
    /* 二期防御: 16 位寄存器宽度 (ref.json TIM5.PSC/ARR bits 0:15) */
    if (psc > 0xFFFFu || arr > 0xFFFFu) {
        return 0u;
    }
    div = (psc + 1u) * (arr + 1u);
    if (div == 0u) {                     /* 满档乘积回绕 → 拒绝 (防除零) */
        return 0u;
    }
    return tim_clk_hz / div;
}

static uint32_t timer_arr_for_hz(uint32_t tim_clk_hz, uint32_t psc,
                                 uint32_t hz)
{
    uint32_t arr;
    /* 二期防御: 零目标频率 (除零) 与 PSC 超宽拒绝 */
    if (hz == 0u || psc > 0xFFFFu) {
        return 0u;
    }
    arr = tim_clk_hz / ((psc + 1u) * hz) - 1u;
    if (arr > 0xFFFFu) {                 /* 二期防御: 16 位 ARR 放不下
                                            (GAP-G-2 家族, 样例侧哨兵) */
        return 0u;
    }
    return arr;
}

/* 配置序列 — target 写真寄存器 / host(F103_MOCK_REGS) 写重定向结构, 两态共用 */
static void tim5_pwm_init(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_TIM5EN;   /* ref.json RCC.APB1ENR bit3 */
    __DSB();
    TIM5->PSC  = 71;                      /* 1MHz */
    TIM5->ARR  = timer_arr_for_hz(72000000u, 71u, 1000u);   /* → 1kHz */
    TIM5->CCR1 = (TIM5->ARR + 1u) / 2u;   /* 50% */
    /* CCMR1_Output: OC1M=110 PWM1 (bits 4:6) + OC1PE (bit3) */
    TIM5->CCMR1 = (6UL << 4) | (1UL << 3);
    TIM5->CCER  = (1UL << 0);             /* CC1E */
    TIM5->CR1   = (1UL << 7) | (1UL << 0);/* ARPE + CEN */
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    tim5_pwm_init();
    if (timer_output_hz(72000000u, 71u, TIM5->ARR) != 1000u) {
        for (;;) {                        /* 配置自洽校验失败 (理论不可达) */
        }
    }
    for (;;) {
        __WFI();
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

int main(void)
{
    /* 换算断言 (期望值手工演算) */
    CHECK(timer_output_hz(72000000u, 71, 999) == 1000u);
    CHECK(timer_output_hz(72000000u, 7199, 9999) == 1u);
    CHECK(timer_output_hz(36000000u, 0, 35) == 1000000u);
    CHECK(timer_arr_for_hz(72000000u, 71u, 1000u) == 999u);
    /* 组1 边界: PSC=0 + ARR 满档 0xFFFF → 72M/65536 = 1098 (截断) */
    CHECK(timer_output_hz(72000000u, 0, 65535) == 1098u);
    /* 组2 防御-除零 (二期新增): hz=0 → 0 哨兵, 不崩 */
    CHECK(timer_arr_for_hz(72000000u, 71u, 0u) == 0u);
    /* 组3 防御-溢出 (二期新增): 72000-1=71999 超 16 位 → 0 哨兵
     * (GAP-G-2 家族); PSC 超宽拒绝; 满档乘积回绕拒绝 */
    CHECK(timer_arr_for_hz(72000000u, 0u, 1000u) == 0u);
    CHECK(timer_arr_for_hz(72000000u, 0x10000u, 1000u) == 0u);
    CHECK(timer_output_hz(72000000u, 0x10000u, 0u) == 0u);
    CHECK(timer_output_hz(72000000u, 0xFFFFu, 0xFFFFu) == 0u);
    /* 配置序列断言 */
    tim5_pwm_init();
    CHECK(f103_mock_RCC.APB1ENR & RCC_APB1ENR_TIM5EN);
    CHECK(f103_mock_TIM5.PSC  == 71u);
    CHECK(f103_mock_TIM5.ARR  == 999u);
    CHECK(f103_mock_TIM5.CCR1 == 500u);
    CHECK(f103_mock_TIM5.CCMR1 == ((6u << 4) | (1u << 3)));
    CHECK(f103_mock_TIM5.CR1  == ((1u << 7) | 1u));
    /* 组4 序列↔换算联动: mock 终态回代换算函数仍得目标频率 */
    CHECK(timer_output_hz(72000000u, f103_mock_TIM5.PSC,
                          f103_mock_TIM5.ARR) == 1000u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
