/* f103-tim6-7 — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: 基本定时器 (无输出通道) 双实例配置 — TIM6 1Hz / TIM7 1kHz,
 *       轮询更新标志; 纯函数 basic_timer_irq_hz 供 host 断言。
 * ref.json anchor: peripherals.TIM6 (base=0x40001000, CR1/CR2/DIER/SR/
 *                  EGR/CNT/PSC/ARR), peripherals.TIM7 (base=0x40001400,
 *                  布局同 TIM6), RCC.APB1ENR bits 4/5=TIM6EN/TIM7EN。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

/* 中断频率换算 (纯函数, host 可测): f = tim_clk/((PSC+1)*(ARR+1)),
 * ARR 由目标频率反解 */
static uint32_t basic_timer_irq_hz(uint32_t tim_clk_hz, uint32_t psc,
                                   uint32_t arr)
{
    return tim_clk_hz / ((psc + 1u) * (arr + 1u));
}

static uint32_t basic_timer_arr_for_hz(uint32_t tim_clk_hz, uint32_t psc,
                                       uint32_t hz)
{
    return tim_clk_hz / ((psc + 1u) * hz) - 1u;
}

/* 配置序列 — target 写真寄存器 / host(F103_MOCK_REGS) 写重定向结构, 两态共用 */
static void tim6_tim7_init(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_TIM6EN | RCC_APB1ENR_TIM7EN;
    __DSB();
    /* TIM6 → 1Hz: 72MHz/7200/10000 */
    TIM6->PSC = 7199u;
    TIM6->ARR = basic_timer_arr_for_hz(72000000u, 7199u, 1u);
    TIM6->CR1 = (1UL << 0);               /* CEN (ref.json TIM6.CR1 bit0) */
    /* TIM7 → 1kHz: 72MHz/720/100 */
    TIM7->PSC = 719u;
    TIM7->ARR = basic_timer_arr_for_hz(72000000u, 719u, 1000u);
    TIM7->CR1 = (1UL << 0);
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    tim6_tim7_init();
    if (basic_timer_irq_hz(72000000u, 7199u, TIM6->ARR) != 1u
            || basic_timer_irq_hz(72000000u, 719u, TIM7->ARR) != 1000u) {
        for (;;) {                        /* 配置自洽校验失败 (理论不可达) */
        }
    }
    for (;;) {
        /* 最小使用场景: 轮询两实例更新标志 (SR bit0=UIF) */
        if (TIM6->SR & 1u) {
            TIM6->SR = 0u;                /* 写 0 清 (rc_w0) */
        }
        if (TIM7->SR & 1u) {
            TIM7->SR = 0u;
        }
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
    CHECK(basic_timer_irq_hz(72000000u, 7199, 9999) == 1u);
    CHECK(basic_timer_irq_hz(72000000u, 719, 99) == 1000u);
    CHECK(basic_timer_arr_for_hz(72000000u, 7199u, 1u) == 9999u);
    /* 双实例序列断言 (互不串扰) */
    tim6_tim7_init();
    CHECK(f103_mock_RCC.APB1ENR & RCC_APB1ENR_TIM6EN);
    CHECK(f103_mock_RCC.APB1ENR & RCC_APB1ENR_TIM7EN);
    CHECK(f103_mock_TIM6.PSC == 7199u && f103_mock_TIM6.ARR == 9999u);
    CHECK(f103_mock_TIM7.PSC == 719u && f103_mock_TIM7.ARR == 99u);
    CHECK(f103_mock_TIM6.CR1 == 1u && f103_mock_TIM7.CR1 == 1u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
