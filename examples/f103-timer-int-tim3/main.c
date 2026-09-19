/* f103-timer-int-tim3 — T1 样例 (编译级)。
 * 用途: TIM3 10ms 更新中断最小样例 (WFI 休眠等中断)。
 * 生成方式: gen_periph --type timer-int --timer TIM3 --period-ms 10
 * ref.json anchor: peripherals.TIM3 (+ NVIC irq=29, ref.json _relationships)
 * 组装变换: 仅两处 — ①生成体裸语句包入 timer_int_tim3_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 3. ISR */
void TIM3_IRQHandler(void) {
    if (TIM3->SR & 1) {          // 更新标志
        TIM3->SR &= ~1;           // 清除标志
        // TODO: 每 10ms 执行的代码
    }
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void timer_int_tim3_init(void) {
/* ========================================================================
 * TIM3 定时中断 — 每 10ms 触发一次
 * TIM_CLK=72MHz, PSC=71, ARR=9999
 * ======================================================================== */

/* 1. 时钟 + NVIC */
RCC->APB1ENR |= RCC_APB1ENR_TIM3EN;
__DSB();
NVIC->ISER[0] = (1UL << 29);  // TIM3_IRQn = 29

/* 2. Timer 配置 */
TIM3->PSC = 71;            // 72MHz/(71+1) = 1000000Hz
TIM3->ARR = 9999;           // → 100Hz (10ms)
TIM3->DIER = 1;                  // 更新中断使能
TIM3->CR1 = 1;                   // 使能

}


int main(void)
{
    timer_int_tim3_init();
    for (;;) {
        __WFI();
    }
}
