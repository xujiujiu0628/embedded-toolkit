/* f103-rtc — T2 手写寄存器级样例 (编译级)。
 * 用途: 备份域解锁 → LSE 起振 → 选 LSE 为 RTC 时钟 → 配置 1Hz → 轮询秒标志。
 * ref.json anchor: peripherals.RTC (CRH/CRL/PRLH/PRLL 位名), RCC.BDCR
 *                  (LSEON/LSERDY/RTCSEL/RTCEN), PWR.CR bit8=DBP,
 *                  RCC.APB1ENR bits 27/28=BKPEN/PWREN。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void rtc_init_1hz(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_PWREN | RCC_APB1ENR_BKPEN;
    __DSB();
    PWR->CR |= PWR_CR_DBP;               /* 备份域写使能 */
    RCC->BDCR |= RCC_BDCR_LSEON;         /* ref.json RCC.BDCR bit0 */
    while (!(RCC->BDCR & RCC_BDCR_LSERDY)) {   /* bit1=LSERDY */
    }
    RCC->BDCR = (RCC->BDCR & ~(3UL << 8))  /* RTCSEL bits 8:9 */
              | RCC_BDCR_RTCSEL_LSE
              | RCC_BDCR_RTCEN;            /* bit15 */
    RTC->CRL |= (1UL << 3);               /* RSF=1 等待同步 (CRL bit3) */
    RTC->CRL |= (1UL << 4);               /* CNF=1 进入配置模式 (bit4) */
    RTC->PRLH = 0;                        /* ref.json RTC.PRLH bits 0:3 */
    RTC->PRLL = 32767;                    /* LSE 32768Hz → 1Hz (bits 0:15) */
    RTC->CRH |= (1UL << 0);               /* SECIE 秒中断使能 (CRH bit0) */
    RTC->CRL &= ~(1UL << 4);              /* CNF=0 退出配置模式 */
    while (RTC->CRL & (1UL << 5)) {       /* 等 RTOFF (bit5) 写完成 */
    }
}

int main(void)
{
    rtc_init_1hz();
    for (;;) {
        /* 最小使用场景: 轮询秒标志并写 1 清除 (CRL bit0=SECF) */
        if (RTC->CRL & (1UL << 0)) {
            RTC->CRL &= ~(1UL << 0);
        }
        __WFI();
    }
}
