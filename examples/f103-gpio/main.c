/* f103-gpio — T1 样例 (编译级)。
 * 用途: PC13 推挽输出 2MHz 最小样例 — GPIOC CRH 位段配置 + BSRR/BRR 翻转。
 * 生成方式: gen_periph --type gpio --pin PC13 --mode out-pp-2mhz
 * ref.json anchor: peripherals.GPIOC (+ RCC.APB2ENR.IOPCEN)
 * 组装变换: 仅两处 — ①生成体裸语句包入 gpio_pc13_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void gpio_pc13_init(void) {
/* PC13 — 通用推挽输出 2MHz */
RCC->APB2ENR |= RCC_APB2ENR_IOPCEN;
__DSB();
GPIOC->CRH &= ~(0xFUL << 20);
GPIOC->CRH |=  (0x2UL << 20);
}


int main(void)
{
    gpio_pc13_init();
    for (;;) {
        /* 最小使用场景: PC13 心跳翻转 (BSRR 置 1 / BRR 清 0) */
        GPIOC->BSRR = (1UL << 13);
        for (volatile int d = 0; d < 200000; d++) {
        }
        GPIOC->BRR = (1UL << 13);
        for (volatile int d = 0; d < 200000; d++) {
        }
    }
}
