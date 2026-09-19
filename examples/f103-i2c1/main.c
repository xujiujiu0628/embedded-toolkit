/* f103-i2c1 — T1 样例 (编译级)。
 * 用途: I2C1 100kHz 标准模式主发送最小样例 (PB6=SCL PB7=SDA), 含错误链。
 * 生成方式: gen_periph --type i2c --i2c I2C1 --speed 100000 --scl PB6 --sda PB7
 * ref.json anchor: peripherals.I2C1 (+ _relationships.I2C1.pins: SCL=B6 SDA=B7)
 * 组装变换: 仅两处 — ①生成体裸语句包入 i2c1_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 4. Poll write helper */
static error_chain_t i2c1_write(uint8_t dev_addr, uint8_t reg, uint8_t data) {
    uint32_t timeout = 100000;
    while (I2C1->SR2 & (1<<1)) {        // wait BUSY=0
        if (--timeout == 0) return ERR_PLAIN(0xE001, "I2C BUSY timeout");
    }
    I2C1->CR1 |= (1<<8);                 // START
    timeout = 100000;
    while (!(I2C1->SR1 & 1)) {           // wait SB
        if (--timeout == 0) return ERR_PLAIN(0xE002, "I2C START timeout");
    }
    I2C1->DR = (dev_addr << 1);          // ADDR + W
    timeout = 100000;
    while (!(I2C1->SR1 & (1<<1))) {       // wait ADDR
        if (--timeout == 0) return ERR_PLAIN(0xE003, "I2C ADDR timeout");
    }
    (void)I2C1->SR2;                       // clear ADDR
    I2C1->DR = reg;                       // send register
    timeout = 100000;
    while (!(I2C1->SR1 & (1<<7))) {       // wait TXE
        if (--timeout == 0) return ERR_PLAIN(0xE004, "I2C TXE timeout");
    }
    I2C1->DR = data;                      // send data
    timeout = 100000;
    while (!(I2C1->SR1 & (1<<7))) {
        if (--timeout == 0) return ERR_PLAIN(0xE004, "I2C TXE timeout");
    }
    timeout = 100000;
    while (!(I2C1->SR1 & (1<<2))) {       // wait BTF
        if (--timeout == 0) return ERR_PLAIN(0xE005, "I2C BTF timeout");
    }
    I2C1->CR1 |= (1<<9);                  // STOP
    return ERR_OK;
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void i2c1_init(void) {
/* ========================================================================
 * I2C1 — 100kHz standard mode, SCL=PB6 SDA=PB7
 * CCR=0x0B4 (180), TRISE=0x25 (37)
 * WARNING: STM32F103 I2C has known errata. Consider software I2C for
 *          production use. See f103_known_issues.json.
 * ======================================================================== */

/* 1. Clock enable */
RCC->APB1ENR |= RCC_APB1ENR_I2C1EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPBEN | RCC_APB2ENR_IOPBEN;
__DSB();

/* 2. GPIO — SCL=PB6 AF-OD, SDA=PB7 AF-OD */
GPIOB->CRL &= ~(0xFUL << 24);
GPIOB->CRL |=  (0xFUL << 24);
GPIOB->CRL &= ~(0xFUL << 28);
GPIOB->CRL |=  (0xFUL << 28);

/* 3. I2C1 config */
I2C1->CR2 = 36;               // FREQ = PCLK1 MHz
I2C1->CCR = 0x0B4;       // 100kHz, CCR=180
I2C1->TRISE = 37;                // max rise time = 37
I2C1->CR1 = 1;                  // PE=1, enable

}


int main(void)
{
    i2c1_init();
    for (;;) {
        /* 最小使用场景: 向 0x68 器件写寄存器 0x00 (错误链回执仅捕获不处理) */
        volatile error_chain_t rc = i2c1_write(0x68, 0x00, 0x01);
        (void)rc;
        for (volatile int d = 0; d < 500000; d++) {
        }
    }
}
