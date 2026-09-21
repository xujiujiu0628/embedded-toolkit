/* f103-spi3 — T1 样例 (编译级)。
 * 用途: SPI3 Mode0 /8 分频主模式参考型样例 — C8T6 无 SPI3 (高密度才有), 引脚与 JTAG 冲突需 AFIO 让位。
 * 生成方式: gen_periph 不支持 SPI3 (GAP-G-1) — 主体 = SPI2 生成物 + 手工适配 (适配行均带 ref.json anchor)
 * ref.json anchor: RCC.APB1ENR.SPI3EN@15 (ref.json RCC); SPI3 基址/引脚见 GAPREPORT GAP-G-1
 * 组装变换: 仅两处 — ①生成体裸语句包入 spi3_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (SPI2 生成物 + 手工适配 (见文件头注记), 文件作用域定义) ── */
/* 4. CS control macros */
#define SPI3_CS_LOW()  GPIOA->BRR = (1UL << 15)
#define SPI3_CS_HIGH() GPIOA->BSRR = (1UL << 15)

/* 5. Poll transfer */
static uint8_t spi3_transfer(uint8_t tx_byte) {
    while (!(SPI3->SR & (1<<1)));  /* wait TXE */
    SPI3->DR = tx_byte;
    while (!(SPI3->SR & (1<<0)));  /* wait RXNE */
    return SPI3->DR;
}

/* 6. Burst write example (F-178/H-3 同源: 逐字节排空 RX) */
static void spi3_write_burst(uint8_t *buf, int len) {
    SPI3_CS_LOW();
    for (int i = 0; i < len; i++) {
        while (!(SPI3->SR & (1<<1)));  /* wait TXE */
        SPI3->DR = buf[i];
        while (!(SPI3->SR & (1<<0)));  /* wait RXNE */
        (void)SPI3->DR;                /* drain RX (清 RXNE, 防 OVR 滞留) */
    }
    while (SPI3->SR & (1<<7));  /* wait BSY=0 */
    SPI3_CS_HIGH();
}

/* ── 生成体 (SPI2 生成物 + 手工适配 (见文件头注记), 裸语句仅包入 init 函数, 行保持原文) ── */
static void spi3_init(void) {
/* ========================================================================
 * SPI3 — Mode 0 (CPOL=0,CPHA=0), 9000kHz
 * SCK=PB3 MISO=PB4 MOSI=PB5 NSS=PA15 (software CS)
 * PCLK=36MHz(APB1), BR[2:0]=2 (/ 8)
 * 注: 本文件主体为 gen_periph SPI2 生成物的手工适配 (GAP-G-1: 生成器
 *     不支持 SPI3)。适配点仅三处, 均锚定 ref.json:
 *     ① RCC_APB1ENR_SPI3EN@15 (ref.json RCC.APB1ENR bits)
 *     ② SPI3 基址 0x40003C00 (f103_regs.h, GAPREPORT 记账)
 *     ③ 引脚 PB3/PB4/PB5/PA15 + AFIO_MAPR.SWJ_CFG 让位 JTAG
 * ======================================================================== */

/* 1. Clock enable — SPI3 挂 APB1 (RCC.APB1ENR.SPI3EN@15), GPIOA/B 同使能 */
RCC->APB1ENR |= RCC_APB1ENR_SPI3EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_IOPBEN | RCC_APB2ENR_AFIOEN;
__DSB();

/* 1b. SWJ_CFG=010 (JTAG-DP 禁用, SW-DP 使能) 让出 PB3/PB4/PA15
 *    (ref.json peripherals.AFIO.registers.MAPR bits 24:26=SWJ_CFG) */
AFIO->MAPR = (AFIO->MAPR & ~(7UL << 24)) | (2UL << 24);

/* 2. GPIO config
 *    SCK=PB3 — AF push-pull 50MHz (CRL[15:12])
 *    MOSI=PB5 — AF push-pull 50MHz (CRL[23:20])
 *    MISO=PB4 — floating input (CRL[19:16])
 *    NSS=PA15 — GPIO output (CRH[31:28]) */
GPIOB->CRL &= ~(0xFUL << 12);
GPIOB->CRL |=  (0xBUL << 12);
GPIOB->CRL &= ~(0xFUL << 16);
GPIOB->CRL |=  (0x4UL << 16);
GPIOB->CRL &= ~(0xFUL << 20);
GPIOB->CRL |=  (0xBUL << 20);
GPIOA->CRH &= ~(0xFUL << 28);
GPIOA->CRH |=  (0x3UL << 28);
GPIOA->BSRR = (1UL << 15);  /* CS=HIGH (inactive) */

/* 3. SPI3 config */
SPI3->CR1 = 0x0014 | (1<<9) | (1<<8);  /* MSTR+SSM+SSI, BR=2 */
SPI3->CR1 |= (1<<6);                   /* SPE=1, enable */

}


int main(void)
{
    spi3_init();
    uint8_t tx[4] = {0xDE, 0xAD, 0xBE, 0xEF};
    spi3_write_burst(tx, 4);
    for (;;) {
        volatile uint8_t rx = spi3_transfer(0x55);
        (void)rx;
        for (volatile int d = 0; d < 100000; d++) {
        }
    }
}
