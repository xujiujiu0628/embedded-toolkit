/* f103-pwr-bkp — T2 手写寄存器级样例 (编译级)。
 * 用途: 使能 PWR/BKP 时钟 → DBP 解锁备份域 → 写读 BKP 备份寄存器。
 * ref.json anchor: peripherals.PWR (CR bit8=DBP), peripherals.BKP
 *                  (DR1..DR42 @+0x04 步进 4 — ref.json 以 0x40006C04
 *                  为 base, 本样例按外设基址 0x40006C00 表达, 绝对地址
 *                  相等, GAP-D-2), RCC.APB1ENR bits 27/28。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void pwr_bkp_init(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_PWREN | RCC_APB1ENR_BKPEN;
    __DSB();
    PWR->CR |= PWR_CR_DBP;                /* 备份域写使能 (ref.json PWR.CR bit8) */
}

int main(void)
{
    pwr_bkp_init();
    uint32_t beat = 0;
    for (;;) {
        /* 最小使用场景: 心跳计数写 DR1, 识别字写 DR2..DR4 (VBAT 之下保持) */
        BKP->DR[0] = (uint16_t)beat++;
        BKP->DR[1] = 0x1234u;
        BKP->DR[2] = 0x5678u;
        BKP->DR[3] = 0x9ABCu;
        for (volatile int d = 0; d < 200000; d++) {
        }
    }
}
