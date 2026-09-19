/* f103-usb — T3 参考型样例 (编译级), 按简报仅做 48MHz 时钟配置链。
 * 用途: HSE 8MHz → PLL ×9 = 72MHz → USBPRE=0 (/1.5) → USB 48MHz,
 *       外设时钟使能。不触 USB 端点寄存器。
 * ref.json anchor: RCC.CR (HSEON@16 HSERDY@17 PLLON@24 PLLRDY@25),
 *                  RCC.CFGR (SW@0:1 SWS@2:3 PLLSRC@16 PLLXTPRE@17
 *                  PLLMUL@18:21 OTGFSPRE@22), RCC.APB1ENR bit23=USBEN。
 * GAP-D-4: PLLMUL 编码表 (0111→×9) 与 USBPRE 分频值语义 (0→/1.5)
 *          为 RM 规定, ref.json 只有位域位置。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void usb_clock_48mhz_init(void)
{
    RCC->CR |= (1UL << 16);              /* HSEON */
    while (!(RCC->CR & (1UL << 17))) {   /* HSERDY */
    }
    RCC->CFGR |= (1UL << 16);            /* PLLSRC=HSE */
    RCC->CFGR &= ~(1UL << 17);           /* PLLXTPRE=0 (HSE 不分频) */
    RCC->CFGR = (RCC->CFGR & ~(0xFUL << 18)) | (7UL << 18);  /* PLLMUL=×9 */
    RCC->CR |= (1UL << 24);              /* PLLON */
    while (!(RCC->CR & (1UL << 25))) {   /* PLLRDY */
    }
    RCC->CFGR = (RCC->CFGR & ~(3UL << 0)) | (2UL << 0);      /* SW=PLL */
    while (((RCC->CFGR >> 2) & 3u) != 2u) {                   /* SWS=PLL */
    }
    RCC->CFGR &= ~(1UL << 22);           /* OTGFSPRE=0 → 72/1.5=48MHz */
    RCC->APB1ENR |= RCC_APB1ENR_USBEN;   /* ref.json RCC.APB1ENR bit23 */
}

int main(void)
{
    usb_clock_48mhz_init();
    for (;;) {
        __WFI();
    }
}
