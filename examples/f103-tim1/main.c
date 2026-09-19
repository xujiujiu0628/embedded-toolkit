/* f103-tim1 — T2 手写寄存器级样例 (编译级)。
 * 用途: 高级定时器 10kHz PWM, 互补通道使能, 死区 + 刹车输入配置,
 *       最后 MOE 主输出使能 (高级定时器专属)。
 * ref.json anchor: peripherals.TIM1 (CCMR1_Output/CCER/BDTR/RCR/EGR 位名),
 *                  _relationships.TIM1.pins (CH1=A8), RCC.APB2ENR bit11。
 * GAP-D-4: CH1N/BKIN 引脚 (PB13/PB12 默认映射) ref.json 未登记, 本样例
 *          只配 CH1 的 GPIO, 互补/刹车引脚需另行按板线确认。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void tim1_complementary_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN | RCC_APB2ENR_IOPAEN;
    __DSB();
    /* CH1=PA8 复用推挽 50MHz (ref.json _relationships.TIM1.pins CH1=A8,
     * CRL 每 pin 4 位 → PA8 在 CRH bits 0:3) */
    GPIOA->CRH &= ~(0xFUL << 0);
    GPIOA->CRH |=  (0xBUL << 0);

    TIM1->PSC  = 71;                      /* 72MHz/72 = 1MHz */
    TIM1->ARR  = 99;                      /* → 10kHz */
    TIM1->CCR1 = 50;                      /* 50% */
    TIM1->RCR  = 0;                       /* ref.json TIM1.RCR bits 0:7 */
    /* CCMR1_Output: OC1M=110 (PWM1) bits 4:6, OC1PE bit3
     * (ref.json TIM1.CCMR1_Output bits) */
    TIM1->CCMR1 = (6UL << 4) | (1UL << 3);
    /* CCER: CC1E@0 CC1P@1 CC1NE@2 CC1NP@3 — 互补对使能 */
    TIM1->CCER = (1UL << 0) | (1UL << 2);
    /* BDTR: DTG@0:7 死区=32*TDTS, BKE@12 刹车使能, MOE@15 主输出 */
    TIM1->BDTR = (32UL << 0) | (1UL << 12) | (1UL << 15);
    TIM1->EGR  = (1UL << 0);              /* UG 生成更新事件重载 */
    TIM1->CR1  = (1UL << 7) | (1UL << 0); /* ARPE + CEN */
}

int main(void)
{
    tim1_complementary_init();
    for (;;) {
        __WFI();                          /* 硬件自主输出 */
    }
}
