/* f103-sdio — T3 参考型样例 (编译级)。
 * 用途: SDIO 外设上电 (POWER) 与时钟分频 (CLKCR) 核心配置;
 *       命令/数据流程需要卡在位, 不在本样例范围。
 * ref.json anchor: peripherals.SDIO (POWER bits 1:0=PWRCTRL, CLKCR
 *                  bits 0:7=CLKDIV 8=CLKEN 11:12=WIDBUS), RCC.AHBENR
 *                  bit10=SDIOEN。
 * GAP-D-4: PWRCTRL 值语义与 CLKDIV 演示值按注释声明, 位号 ref.json 在案。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void sdio_power_clock_init(void)
{
    RCC->AHBENR |= RCC_AHBENR_SDIOEN;    /* ref.json RCC.AHBENR bit10 */
    __DSB();
    SDIO->POWER = 3u;                    /* PWRCTRL=11 上电 (bits 1:0) */
    SDIO->CLKCR = (0x1FUL << 0)          /* CLKDIV 演示值 (bits 0:7) */
                | (1UL << 8);            /* CLKEN 时钟输出使能 (bit8) */
}

int main(void)
{
    sdio_power_clock_init();
    for (;;) {
        __WFI();
    }
}
