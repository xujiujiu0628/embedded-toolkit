/* f103-usart2 — T1 样例 (编译级)。
 * 用途: USART2 115200-8N1 轮询收发最小样例 (PA2=TX PA3=RX)。
 * 生成方式: gen_periph --type usart --usart USART2 --baud 115200 --tx PA2 --rx PA3
 * ref.json anchor: peripherals.USART2 (+ _relationships.USART2.pins: TX=A2 RX=A3)
 * 组装变换: 仅两处 — ①生成体裸语句包入 usart2_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 4. printf 重定向 (GCC/newlib-nano 系统桩 _write; Keil Microlib 的 fputc 在此链不生效) */
#include <unistd.h>
int _write(int fd, char *buf, int len) {
    for (int i = 0; i < len; i++) {
        while (!(USART2->SR & (1UL<<7)));  // wait TXE
        USART2->DR = (uint8_t)buf[i];
    }
    return len;
}

/* 5. 轮询读写 */
static void uart_putc(uint8_t byte) {
    while (!(USART2->SR & (1UL<<7)));
    USART2->DR = byte;
}
static uint8_t uart_getc(void) {
    while (!(USART2->SR & (1UL<<5)));  // wait RXNE
    return USART2->DR;
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void usart2_init(void) {
/* ========================================================================
 * USART2 — 115200 baud, 8N1, TX=PA2 RX=PA3
 * PCLK1=36MHz, BRR=0x0138 (19.8/16)
 * ======================================================================== */

/* 1. 时钟使能 */
RCC->APB1ENR |= RCC_APB1ENR_USART2EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;
__DSB();

/* 2. GPIO 配置 */
// PA2 = USART2_TX (复用推挽 50MHz)
GPIOA->CRL &= ~(0xFUL << 8);
GPIOA->CRL |=  (0xBUL << 8);
// PA3 = USART2_RX (浮空输入)
GPIOA->CRL &= ~(0xFUL << 12);
GPIOA->CRL |=  (0x4UL << 12);

/* 3. USART 配置 */
USART2->BRR = 0x0138;
USART2->CR1 = USART_CR1_TE | USART_CR1_RE;
USART2->CR1 |= USART_CR1_UE;

}


int main(void)
{
    usart2_init();
    for (;;) {
        const char *msg = "USART2 OK\r\n";
        for (int i = 0; msg[i]; i++) {
            uart_putc((uint8_t)msg[i]);
        }
        if (USART2->SR & (1UL << 5)) {   /* ref.json USART2.SR bit5=RXNE */
            volatile uint8_t echo = uart_getc();
            (void)echo;
        }
        for (volatile int d = 0; d < 500000; d++) {
        }
    }
}
