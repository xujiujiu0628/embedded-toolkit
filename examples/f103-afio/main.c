/* f103-afio — T2 手写寄存器级样例 (编译级)。
 * 用途: AFIO 三件事演示 — EXTI 线到端口的路由 (EXTICR)、外设重映射
 *       (MAPR)、SWJ 调试口配置 (MAPR bits 24:26, 写只读读)。
 * ref.json anchor: peripherals.AFIO (MAPR/EXTICR1/EVCR/MAPR2 位名),
 *                  RCC.APB2ENR bit0=AFIOEN。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void afio_demo(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_AFIOEN | RCC_APB2ENR_IOPAEN;
    __DSB();
    /* EXTI0 路由到 PA0: EXTICR1 bits 0:3 = 0000 → PA
     * (ref.json AFIO.EXTICR1 bits 0:3=EXTI0) */
    AFIO->EXTICR1 &= ~(0xFUL << 0);
    /* TIM2 CH1/CH2 不重映射 (MAPR bits 8:9=TIM2_REMAP 保持 00):
     * ref.json AFIO.MAPR bits 8:9 — 保持默认 PA0/PA1 */
    AFIO->MAPR &= ~((3UL << 8) | (3UL << 10));   /* TIM2/TIM3_REMAP=00 */
    /* SWJ_CFG=000 完整 SWJ (JTAG+SWD): bits 24:26 写只读读
     * (ref.json AFIO.MAPR bits 24:26=SWJ_CFG) */
    AFIO->MAPR &= ~(7UL << 24);
}

int main(void)
{
    afio_demo();
    for (;;) {
        __WFI();
    }
}
