/* f103-exti — T2 手写寄存器级样例 (编译级)。
 * 用途: PA0 上升沿触发 EXTI0 中断, ISR 内清挂起标志。
 * ref.json anchor: peripherals.EXTI (IMR/RTSR/PR 位名), peripherals.AFIO
 *                  (EXTICR1 bits 0:3=EXTI0), peripherals.GPIOA。
 * IRQ 槽位: EXTI0 = 6 — ref.json 无 EXTI 的 IRQ 条目 (GAP-D-3)。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static volatile uint32_t exti0_hits;

void EXTI0_IRQHandler(void)          /* startup.c weak alias 的强符号覆盖 */
{
    if (EXTI->PR & (1UL << 0)) {     /* ref.json EXTI.PR bit0=PR0 */
        EXTI->PR |= (1UL << 0);      /* 写 1 清除挂起 (rc_w1) */
        exti0_hits++;
    }
}

static void exti0_pa0_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_AFIOEN;
    __DSB();
    GPIOA->CRL &= ~(0xFUL << 0);     /* PA0 CNF=01(浮空输入) MODE=00 */
    GPIOA->CRL |=  (0x4UL << 0);     /* ref.json GPIOA.CRL: 每 pin 4 位 */
    AFIO->EXTICR1 &= ~(0xFUL << 0);  /* ref.json AFIO.EXTICR1 bits 0:3=EXTI0 */
    EXTI->IMR |= (1UL << 0);         /* ref.json EXTI.IMR bit0=MR0 非屏蔽 */
    EXTI->RTSR |= (1UL << 0);        /* ref.json EXTI.RTSR bit0=TR0 上升沿 */
    EXTI->FTSR &= ~(1UL << 0);       /* 禁下降沿 */
    NVIC->ISER[0] = (1UL << 6);      /* EXTI0 IRQ — GAP-D-3 槽位 6 */
}

int main(void)
{
    exti0_pa0_init();
    for (;;) {
        __WFI();                     /* 最小使用场景: 每次沿唤醒 */
    }
}
