/* f103-pwm-tim4 — T1 样例 (编译级)。
 * 用途: TIM4 CH1 (PB6) 1000Hz 50% 占空比 PWM 输出最小样例。
 * 生成方式: gen_periph --type pwm --timer TIM4 --ch 1 --freq 1000 --duty 50
 * ref.json anchor: peripherals.TIM4 (+ _relationships.TIM4.pins / RCC.APB1ENR.TIM4EN)
 * 组装变换: 仅两处 — ①生成体裸语句包入 pwm_tim4_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void pwm_tim4_init(void) {
/* ========================================================================
 * TIM4 CH1 PWM — PB6, 1000Hz, 50% duty
 * TIM_CLK=72MHz, PSC=71, ARR=999, CCR1=500 
 * ======================================================================== */

/* 1. 时钟使能 */
RCC->APB1ENR |= RCC_APB1ENR_TIM4EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;
__DSB();

/* 2. GPIO — PB6 复用推挽 50MHz */
GPIOB->CRL &= ~(0xFUL << 24);
GPIOB->CRL |=  (0xBUL << 24);

/* 3. Timer 配置 */
TIM4->PSC = 71;            // 72MHz/(71+1) = 1000000Hz
TIM4->ARR = 999;           // → 1000Hz
TIM4->CCR1 = 500;            // 50% duty
TIM4->CCMR1 = (6<<4) | (1<<3);  // CH1: PWM mode 1, preload
TIM4->CCER  |= (1<<0);           // CH1 output enable
TIM4->CR1 = (1<<7) | 1;        // ARPE + enable
}


int main(void)
{
    pwm_tim4_init();
    for (;;) {
        __WFI();
    }
}
