/* f103-usart3 — T1 样例 (编译级)。
 * 用途: USART3 115200-8N1 轮询收发最小样例 (PB10=TX PB11=RX)。
 * 生成方式: gen_periph --type usart --usart USART3 --baud 115200 --tx PB10 --rx PB11
 * ref.json anchor: peripherals.USART3 (+ _relationships.USART3.pins: TX=B10 RX=B11)
 * 组装变换: 仅两处 — ①生成体裸语句包入 usart3_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 4. printf 重定向 (GCC/newlib-nano 系统桩 _write; Keil Microlib 的 fputc 在此链不生效) */
#include <unistd.h>
int _write(int fd, char *buf, int len) {
    for (int i = 0; i < len; i++) {
        while (!(USART3->SR & (1UL<<7)));  // wait TXE
        USART3->DR = (uint8_t)buf[i];
    }
    return len;
}

/* 5. 轮询读写 */
static void uart_putc(uint8_t byte) {
    while (!(USART3->SR & (1UL<<7)));
    USART3->DR = byte;
}
static uint8_t uart_getc(void) {
    while (!(USART3->SR & (1UL<<5)));  // wait RXNE
    return USART3->DR;
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void usart3_init(void) {
/* ========================================================================
 * USART3 — 115200 baud, 8N1, TX=PB10 RX=PB11
 * PCLK1=36MHz, BRR=0x0138 (19.8/16)
 * ======================================================================== */

/* 1. 时钟使能 */
RCC->APB1ENR |= RCC_APB1ENR_USART3EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;
__DSB();

/* 2. GPIO 配置 */
// PB10 = USART3_TX (复用推挽 50MHz)
GPIOB->CRH &= ~(0xFUL << 8);
GPIOB->CRH |=  (0xBUL << 8);
// PB11 = USART3_RX (浮空输入)
GPIOB->CRH &= ~(0xFUL << 12);
GPIOB->CRH |=  (0x4UL << 12);

/* 3. USART 配置 */
USART3->BRR = 0x0138;
USART3->CR1 = USART_CR1_TE | USART_CR1_RE;
USART3->CR1 |= USART_CR1_UE;

}


int main(void)
{
    usart3_init();
    for (;;) {
        const char *msg = "USART3 OK\r\n";
        for (int i = 0; msg[i]; i++) {
            uart_putc((uint8_t)msg[i]);
        }
        if (USART3->SR & (1UL << 5)) {   /* ref.json USART3.SR bit5=RXNE */
            volatile uint8_t echo = uart_getc();
            (void)echo;
        }
        for (volatile int d = 0; d < 500000; d++) {
        }
    }
}
