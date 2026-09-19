/* f103-tim9-14 — T2 手写寄存器级样例 (编译级)。
 * 用途: TIM9 (双通道) 与 TIM10 (单通道) PWM 配置实做; TIM11~14 为同构
 *       变体, 实例差异 (基址/总线/使能位) 见 README 表。
 * ref.json anchor: peripherals.TIM9/TIM10 (寄存器布局), RCC.APB2ENR
 *                  bits 19/20/21=TIM9EN/TIM10EN/TIM11EN, RCC.APB1ENR
 *                  bits 6/7/8=TIM12EN/TIM13EN/TIM14EN。
 * GAP-D-5: ref.json 外设条目的 bus 字段 (TIM9=APB1, TIM12/13/14=APB2)
 *          与其 RCC 使能位归属矛盾 — 本样例一律以 RCC 位数据为准。
 * 硬件验收: 未做（编译级样例）
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

int main(void)
{
    tim9_dual_pwm_init();
    tim10_pwm_init();
    for (;;) {
        __WFI();
    }
}
