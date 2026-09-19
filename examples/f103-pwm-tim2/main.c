/* f103-pwm-tim2 — T1 样例 (编译级)。
 * 用途: TIM2 CH1 (PA0) 1000Hz 50% 占空比 PWM 输出最小样例。
 * 生成方式: gen_periph --type pwm --timer TIM2 --ch 1 --freq 1000 --duty 50
 * ref.json anchor: peripherals.TIM2 (+ _relationships.TIM2.pins / RCC.APB1ENR.TIM2EN)
 * 组装变换: 仅两处 — ①生成体裸语句包入 pwm_tim2_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void pwm_tim2_init(void) {
/* ========================================================================
 * TIM2 CH1 PWM — PA0, 1000Hz, 50% duty
 * TIM_CLK=72MHz, PSC=71, ARR=999, CCR1=500 
 * ======================================================================== */

/* 1. 时钟使能 */
RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;
__DSB();

/* 2. GPIO — PA0 复用推挽 50MHz */
GPIOA->CRL &= ~(0xFUL << 0);
GPIOA->CRL |=  (0xBUL << 0);

/* 3. Timer 配置 */
TIM2->PSC = 71;            // 72MHz/(71+1) = 1000000Hz
TIM2->ARR = 999;           // → 1000Hz
TIM2->CCR1 = 500;            // 50% duty
TIM2->CCMR1 = (6<<4) | (1<<3);  // CH1: PWM mode 1, preload
TIM2->CCER  |= (1<<0);           // CH1 output enable
TIM2->CR1 = (1<<7) | 1;        // ARPE + enable
}


int main(void)
{
    pwm_tim2_init();
    /* 最小使用场景: 硬件自主输出 PWM, CPU 空转即可 (改占空比写 TIM2->CCR1) */
    for (;;) {
        __WFI();
    }
}
