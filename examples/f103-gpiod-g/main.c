/* f103-gpiod-g — T3 参考型样例 (编译级)。
 * 用途: 高密度芯片的 GPIOD/E/F/G 四端口各配一个推挽输出并翻转,
 *       展示同一 GPIO_TypeDef 布局在 D~G 端口的一致用法。
 * ref.json anchor: peripherals.GPIOD/GPIOE/GPIOF/GPIOG (base 分别
 *                  0x40011400/0x40011800/0x40011C00/0x40012000,
 *                  available_on_c8 均=false), RCC.APB2ENR
 *                  bits 5/6/7/8=IOPDEN/IOPEEN/IOPFEN/IOPGEN。
 * 引脚号 PD0/PE0/PF0/PG0 为演示选择 (非数据断言); 板级接线另查原理图。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void gpiod_e_f_g_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_IOPDEN | RCC_APB2ENR_IOPEEN
                  | RCC_APB2ENR_IOPFEN | RCC_APB2ENR_IOPGEN;
    __DSB();
    /* 每 pin 4 位 (ref.json GPIOx.CRL): CNF=00 推挽 MODE=11 50MHz → 0x3 */
    GPIOD->CRL &= ~(0xFUL << 0);
    GPIOD->CRL |=  (0x3UL << 0);         /* PD0 */
    GPIOE->CRL &= ~(0xFUL << 0);
    GPIOE->CRL |=  (0x3UL << 0);         /* PE0 */
    GPIOF->CRL &= ~(0xFUL << 0);
    GPIOF->CRL |=  (0x3UL << 0);         /* PF0 */
    GPIOG->CRL &= ~(0xFUL << 0);
    GPIOG->CRL |=  (0x3UL << 0);         /* PG0 */
}

int main(void)
{
    gpiod_e_f_g_init();
    for (;;) {
        /* 最小使用场景: 四端口同步心跳翻转 (BSRR 置位 / BRR 清位) */
        GPIOD->BSRR = (1UL << 0);
        GPIOE->BSRR = (1UL << 0);
        GPIOF->BSRR = (1UL << 0);
        GPIOG->BSRR = (1UL << 0);
        for (volatile int d = 0; d < 200000; d++) {
        }
        GPIOD->BRR = (1UL << 0);
        GPIOE->BRR = (1UL << 0);
        GPIOF->BRR = (1UL << 0);
        GPIOG->BRR = (1UL << 0);
        for (volatile int d = 0; d < 200000; d++) {
        }
    }
}
