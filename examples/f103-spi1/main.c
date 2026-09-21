/* f103-spi1 — T1 样例 (编译级)。
 * 用途: SPI1 Mode0 /8 分频主模式最小样例 (软件 CS); write_burst 逐字节排空 RX
 *       (F-178/H-3 已修 — 原 GAPREPORT GAP-S-1 注销)。
 * 生成方式: gen_periph --type spi --spi SPI1 --spi-mode 0 --baud-div 8 --sck PA5 --miso PA6 --mosi PA7 --nss PA4
 * ref.json anchor: peripherals.SPI1 (+ _relationships.SPI1.pins: NSS=A4 SCK=A5 MISO=A6 MOSI=A7)
 * 组装变换: 仅两处 — ①生成体裸语句包入 spi1_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 4. CS control macros */
#define SPI1_CS_LOW()  GPIOA->BRR = (1UL << 4)
#define SPI1_CS_HIGH() GPIOA->BSRR = (1UL << 4)

/* 5. Poll transfer */
static uint8_t spi1_transfer(uint8_t tx_byte) {
    while (!(SPI1->SR & (1<<1)));  // wait TXE
    SPI1->DR = tx_byte;
    while (!(SPI1->SR & (1<<0)));  // wait RXNE
    return SPI1->DR;
}

/* 6. Burst write example */
static void spi1_write_burst(uint8_t *buf, int len) {
    SPI1_CS_LOW();
    for (int i = 0; i < len; i++) {
        while (!(SPI1->SR & (1<<1)));  // wait TXE
        SPI1->DR = buf[i];
        while (!(SPI1->SR & (1<<0)));  // wait RXNE
        (void)SPI1->DR;                // drain RX (清 RXNE, 防 OVR 滞留)
    }
    while (SPI1->SR & (1<<7));  // wait BSY=0
    SPI1_CS_HIGH();
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void spi1_init(void) {
/* ========================================================================
 * SPI1 — Mode 0 (CPOL=0,CPHA=0), 9000kHz
 * SCK=PA5 MISO=PA6 MOSI=PA7 NSS=PA4 (software CS)
 * PCLK=72MHz, BR[2:0]=2 (/ 8)
 * ======================================================================== */

/* 1. Clock enable */
RCC->APB2ENR |= RCC_APB2ENR_SPI1EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;
__DSB();

/* 2. GPIO config */
// SCK=PA5 — AF push-pull 50MHz
GPIOA->CRL &= ~(0xFUL << 20);
GPIOA->CRL |=  (0xBUL << 20);
// MOSI=PA7 — AF push-pull 50MHz
GPIOA->CRL &= ~(0xFUL << 28);
GPIOA->CRL |=  (0xBUL << 28);
// MISO=PA6 — floating input
GPIOA->CRL &= ~(0xFUL << 24);
GPIOA->CRL |=  (0x4UL << 24);
// NSS=PA4 — GPIO output (software CS)
GPIOA->CRL &= ~(0xFUL << 16);
GPIOA->CRL |=  (0x3UL << 16);
GPIOA->BSRR = (1UL << 4);  // CS=HIGH (inactive)

/* 3. SPI1 config */
// CR1: BR[2:0]=2 CPOL=0 CPHA=0 MSTR=1 SSM=1 SSI=1
SPI1->CR1 = 0x0014 | (1<<9) | (1<<8);  // SSM+SSI (software NSS)
// CR2: SSOE=0 (output disabled, manual CS)
SPI1->CR1 |= (1<<6);                        // SPE=1, enable

}


int main(void)
{
    spi1_init();
    /* write_burst 一次 (F-178/H-3: 每写一字节 wait RXNE 并读回 DR,
     * 不再留 OVR/RXNE 残留 — 紧随其后的 transfer 读到的是本次真收字节) */
    uint8_t tx[4] = {0xDE, 0xAD, 0xBE, 0xEF};
    spi1_write_burst(tx, 4);
    for (;;) {
        /* 最小使用场景: 全双工回环一字节 */
        volatile uint8_t rx = spi1_transfer(0x55);
        (void)rx;
        for (volatile int d = 0; d < 100000; d++) {
        }
    }
}
