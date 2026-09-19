/* f103-spi2 — T1 样例 (编译级)。
 * 用途: SPI2 Mode0 /8 分频主模式最小样例 (软件 CS), 已知 write_burst 不排空 RX (见 GAPREPORT GAP-S-1)。
 * 生成方式: gen_periph --type spi --spi SPI2 --spi-mode 0 --baud-div 8 --sck PB13 --miso PB14 --mosi PB15 --nss PB12
 * ref.json anchor: peripherals.SPI2 (+ _relationships.SPI2.pins: NSS=B12 SCK=B13 MISO=B14 MOSI=B15)
 * 组装变换: 仅两处 — ①生成体裸语句包入 spi2_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 4. CS control macros */
#define SPI2_CS_LOW()  GPIOB->BRR = (1UL << 12)
#define SPI2_CS_HIGH() GPIOB->BSRR = (1UL << 12)

/* 5. Poll transfer */
static uint8_t spi2_transfer(uint8_t tx_byte) {
    while (!(SPI2->SR & (1<<1)));  // wait TXE
    SPI2->DR = tx_byte;
    while (!(SPI2->SR & (1<<0)));  // wait RXNE
    return SPI2->DR;
}

/* 6. Burst write example */
static void spi2_write_burst(uint8_t *buf, int len) {
    SPI2_CS_LOW();
    for (int i = 0; i < len; i++) {
        while (!(SPI2->SR & (1<<1)));
        SPI2->DR = buf[i];
    }
    while (SPI2->SR & (1<<7));  // wait BSY=0
    SPI2_CS_HIGH();
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void spi2_init(void) {
/* ========================================================================
 * SPI2 — Mode 0 (CPOL=0,CPHA=0), 4500kHz
 * SCK=PB13 MISO=PB14 MOSI=PB15 NSS=PB12 (software CS)
 * PCLK=36MHz, BR[2:0]=2 (/ 8)
 * ======================================================================== */

/* 1. Clock enable */
RCC->APB1ENR |= RCC_APB1ENR_SPI2EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;
__DSB();

/* 2. GPIO config */
// SCK=PB13 — AF push-pull 50MHz
GPIOB->CRH &= ~(0xFUL << 20);
GPIOB->CRH |=  (0xBUL << 20);
// MOSI=PB15 — AF push-pull 50MHz
GPIOB->CRH &= ~(0xFUL << 28);
GPIOB->CRH |=  (0xBUL << 28);
// MISO=PB14 — floating input
GPIOB->CRH &= ~(0xFUL << 24);
GPIOB->CRH |=  (0x4UL << 24);
// NSS=PB12 — GPIO output (software CS)
GPIOB->CRH &= ~(0xFUL << 16);
GPIOB->CRH |=  (0x3UL << 16);
GPIOB->BSRR = (1UL << 12);  // CS=HIGH (inactive)

/* 3. SPI2 config */
// CR1: BR[2:0]=2 CPOL=0 CPHA=0 MSTR=1 SSM=1 SSI=1
SPI2->CR1 = 0x0014 | (1<<9) | (1<<8);  // SSM+SSI (software NSS)
// CR2: SSOE=0 (output disabled, manual CS)
SPI2->CR1 |= (1<<6);                        // SPE=1, enable

}


int main(void)
{
    spi2_init();
    uint8_t tx[4] = {0xDE, 0xAD, 0xBE, 0xEF};
    spi2_write_burst(tx, 4);
    for (;;) {
        volatile uint8_t rx = spi2_transfer(0x55);
        (void)rx;
        for (volatile int d = 0; d < 100000; d++) {
        }
    }
}
