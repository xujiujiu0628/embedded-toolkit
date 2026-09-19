/* f103-tim8 — T2 手写寄存器级样例 (编译级)。
 * 用途: 高级定时器 TIM8 与 TIM1 寄存器布局一致 — 本样例演示实例级
 *       差异 (基址/时钟位/IRQ), 核心配置序列与 f103-tim1 同模板。
 * ref.json anchor: peripherals.TIM8 (base=0x40013400, 寄存器布局同 TIM1),
 *                  RCC.APB2ENR bit13=TIM8EN。
 * 与 TIM1 的差异 (README 详表): APB2ENR 位 13 vs 11; 向量槽位
 * 43/44/45 (TIM8_BRK_TIM12/TIM8_UP_TIM13/TIM8_TRG_COM_TIM14, GAP-D-3);
 * 无 _relationships 引脚条目 → 本样例不配 GPIO。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void tim8_pwm_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_TIM8EN;   /* ref.json RCC.APB2ENR bit13 */
    __DSB();
    TIM8->PSC  = 71;                      /* 1MHz 计数 */
    TIM8->ARR  = 999;                     /* → 1kHz */
    TIM8->CCR1 = 500;                     /* 50% */
    TIM8->RCR  = 0;
    TIM8->CCMR1 = (6UL << 4) | (1UL << 3);/* OC1M=PWM1 + 预装载 */
    TIM8->CCER  = (1UL << 0);             /* CC1E (无 GPIO, 核心级使能) */
    TIM8->BDTR  = (1UL << 15);            /* MOE (高级定时器必须) */
    TIM8->EGR   = (1UL << 0);             /* UG */
    TIM8->CR1   = (1UL << 7) | (1UL << 0);
}

int main(void)
{
    tim8_pwm_init();
    for (;;) {
        __WFI();
    }
}
