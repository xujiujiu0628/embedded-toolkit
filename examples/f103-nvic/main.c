/* f103-nvic — T2 手写寄存器级样例 (编译级)。
 * 用途: NVIC 使能/禁用/优先级写入演示, 以 TIM2 更新中断 (IRQ 28) 为例。
 * ref.json anchor: peripherals.NVIC (ISER@0xE000E100 — ref.json 仅登记
 *                  此寄存器); ICER/IABR/IP 为 Cortex-M3 架构定义
 *                  (GAP-D-1 已记账); TIM2 irq=28 来自
 *                  ref.json _relationships.TIM2.irq。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void nvic_tim2_demo(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;   /* 中断源时钟 */
    __DSB();
    NVIC->IP[28] = 0x40u;                 /* 抢占优先级 1 (IP 按字节宽) */
    NVIC->ISER[0] = (1UL << 28);          /* 使能 TIM2 IRQ (写 1 置位) */
    NVIC->ICER[0] = (1UL << 28);          /* 禁用 (写 1 清位) */
    NVIC->ISER[0] = (1UL << 28);          /* 再使能 */
}

int main(void)
{
    nvic_tim2_demo();
    for (;;) {
        __WFI();                          /* TIM2 未配置即无中断, 演示宿主 */
    }
}
