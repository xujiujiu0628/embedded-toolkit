/* f103-timer-int-tim4 — T1 样例 (编译级)。
 * 用途: TIM4 10ms 更新中断最小样例 (WFI 休眠等中断)。
 * 生成方式: gen_periph --type timer-int --timer TIM4 --period-ms 10
 * ref.json anchor: peripherals.TIM4 (+ NVIC irq=30, ref.json _relationships)
 * 组装变换: 仅两处 — ①生成体裸语句包入 timer_int_tim4_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 3. ISR */
void TIM4_IRQHandler(void) {
    if (TIM4->SR & 1) {          // 更新标志
        TIM4->SR &= ~1;           // 清除标志
        // TODO: 每 10ms 执行的代码
    }
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void timer_int_tim4_init(void) {
/* ========================================================================
 * TIM4 定时中断 — 每 10ms 触发一次
 * TIM_CLK=72MHz, PSC=71, ARR=9999
 * ======================================================================== */

/* 1. 时钟 + NVIC */
RCC->APB1ENR |= RCC_APB1ENR_TIM4EN;
__DSB();
NVIC->ISER[0] = (1UL << 30);  // TIM4_IRQn = 30

/* 2. Timer 配置 */
TIM4->PSC = 71;            // 72MHz/(71+1) = 1000000Hz
TIM4->ARR = 9999;           // → 100Hz (10ms)
TIM4->DIER = 1;                  // 更新中断使能
TIM4->CR1 = 1;                   // 使能

}


int main(void)
{
    timer_int_tim4_init();
    for (;;) {
        __WFI();
    }
}
