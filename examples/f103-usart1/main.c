/* f103-usart1 — T1 样例 (编译级)。
 * 用途: USART1 115200-8N1 轮询收发最小样例 (PA9=TX PA10=RX), 含 _write 重定向。
 * 生成方式: gen_periph --type usart --usart USART1 --baud 115200 --tx PA9 --rx PA10
 * ref.json anchor: peripherals.USART1 (+ _relationships.USART1.pins: TX=A9 RX=A10)
 * 组装变换: 仅两处 — ①生成体裸语句包入 usart1_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 4. printf 重定向 (GCC/newlib-nano 系统桩 _write; Keil Microlib 的 fputc 在此链不生效) */
#include <unistd.h>
int _write(int fd, char *buf, int len) {
    for (int i = 0; i < len; i++) {
        while (!(USART1->SR & (1UL<<7)));  // wait TXE
        USART1->DR = (uint8_t)buf[i];
    }
    return len;
}

/* 5. 轮询读写 */
static void uart_putc(uint8_t byte) {
    while (!(USART1->SR & (1UL<<7)));
    USART1->DR = byte;
}
static uint8_t uart_getc(void) {
    while (!(USART1->SR & (1UL<<5)));  // wait RXNE
    return USART1->DR;
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void usart1_init(void) {
/* ========================================================================
 * USART1 — 115200 baud, 8N1, TX=PA9 RX=PA10
 * PCLK2=72MHz, BRR=0x0271 (39.1/16)
 * ======================================================================== */

/* 1. 时钟使能 */
RCC->APB2ENR |= RCC_APB2ENR_USART1EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;
__DSB();

/* 2. GPIO 配置 */
// PA9 = USART1_TX (复用推挽 50MHz)
GPIOA->CRH &= ~(0xFUL << 4);
GPIOA->CRH |=  (0xBUL << 4);
// PA10 = USART1_RX (浮空输入)
GPIOA->CRH &= ~(0xFUL << 8);
GPIOA->CRH |=  (0x4UL << 8);

/* 3. USART 配置 */
USART1->BRR = 0x0271;
USART1->CR1 = USART_CR1_TE | USART_CR1_RE;
USART1->CR1 |= USART_CR1_UE;

}


int main(void)
{
    usart1_init();
    for (;;) {
        /* 最小使用场景: 周期性发送识别串; RXNE 在场时回读一字节 (uart_getc) */
        const char *msg = "USART1 OK\r\n";
        for (int i = 0; msg[i]; i++) {
            uart_putc((uint8_t)msg[i]);
        }
        if (USART1->SR & (1UL << 5)) {   /* ref.json USART1.SR bit5=RXNE */
            volatile uint8_t echo = uart_getc();
            (void)echo;
        }
        for (volatile int d = 0; d < 500000; d++) {
        }
    }
}
