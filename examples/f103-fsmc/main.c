/* f103-fsmc — T3 参考型样例 (编译级)。
 * 用途: FSMC 存储块 1 使能 + 读时序寄存器配置 (外部 SRAM/NOR 场景)。
 * ref.json anchor: peripherals.FSMC (BCR1@0x00 bits: 19=使能位,
 *                  BTR1@0x04 bits 0:3=ADDSET 4:7=DATAST 8:15=HOLD?-
 *                  位名 ref.json 未登记 (GAP-D-4), 位号在案),
 *                  RCC.AHBENR bit8=FSMCEN。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void fsmc_bank1_sram_init(void)
{
    RCC->AHBENR |= RCC_AHBENR_FSMCEN;    /* ref.json RCC.AHBENR bit8 */
    __DSB();
    FSMC->BTR1 = (1UL << 0)              /* ADDSET=1 HCLK (bits 0:3) */
               | (3UL << 8);             /* DATAST=3 (bits 8:15 域内演示值) */
    FSMC->BCR1 = (1UL << 19)             /* bit19 = 存储块使能 (MBKEN, 位名 GAP-D-4) */
               | (1UL << 12);            /* bit12 演示置位 (宽度域, 位名 GAP-D-4) */
}

int main(void)
{
    fsmc_bank1_sram_init();
    for (;;) {
        __WFI();
    }
}
