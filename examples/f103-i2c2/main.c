/* f103-i2c2 — T1 样例 (编译级)。
 * 用途: I2C2 100kHz 标准模式主发送最小样例 (PB10=SCL PB11=SDA), 含错误链。
 * 生成方式: gen_periph --type i2c --i2c I2C2 --speed 100000 --scl PB10 --sda PB11
 * ref.json anchor: peripherals.I2C2 (+ _relationships.I2C2.pins: SCL=B10 SDA=B11)
 * 组装变换: 仅两处 — ①生成体裸语句包入 i2c2_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 4. Poll write helper */
static error_chain_t i2c2_write(uint8_t dev_addr, uint8_t reg, uint8_t data) {
    uint32_t timeout = 100000;
    while (I2C2->SR2 & (1<<1)) {        // wait BUSY=0
        if (--timeout == 0) return ERR_PLAIN(0xE001, "I2C BUSY timeout");
    }
    I2C2->CR1 |= (1<<8);                 // START
    timeout = 100000;
    while (!(I2C2->SR1 & 1)) {           // wait SB
        if (--timeout == 0) return ERR_PLAIN(0xE002, "I2C START timeout");
    }
    I2C2->DR = (dev_addr << 1);          // ADDR + W
    timeout = 100000;
    while (!(I2C2->SR1 & (1<<1))) {       // wait ADDR
        if (--timeout == 0) return ERR_PLAIN(0xE003, "I2C ADDR timeout");
    }
    (void)I2C2->SR2;                       // clear ADDR
    I2C2->DR = reg;                       // send register
    timeout = 100000;
    while (!(I2C2->SR1 & (1<<7))) {       // wait TXE
        if (--timeout == 0) return ERR_PLAIN(0xE004, "I2C TXE timeout");
    }
    I2C2->DR = data;                      // send data
    timeout = 100000;
    while (!(I2C2->SR1 & (1<<7))) {
        if (--timeout == 0) return ERR_PLAIN(0xE004, "I2C TXE timeout");
    }
    timeout = 100000;
    while (!(I2C2->SR1 & (1<<2))) {       // wait BTF
        if (--timeout == 0) return ERR_PLAIN(0xE005, "I2C BTF timeout");
    }
    I2C2->CR1 |= (1<<9);                  // STOP
    return ERR_OK;
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void i2c2_init(void) {
/* ========================================================================
 * I2C2 — 100kHz standard mode, SCL=PB10 SDA=PB11
 * CCR=0x0B4 (180), TRISE=0x25 (37)
 * WARNING: STM32F103 I2C has known errata. Consider software I2C for
 *          production use. See f103_known_issues.json.
 * ======================================================================== */

/* 1. Clock enable */
RCC->APB1ENR |= RCC_APB1ENR_I2C2EN;
RCC->APB2ENR |= RCC_APB2ENR_IOPBEN | RCC_APB2ENR_IOPBEN;
__DSB();

/* 2. GPIO — SCL=PB10 AF-OD, SDA=PB11 AF-OD */
GPIOB->CRH &= ~(0xFUL << 8);
GPIOB->CRH |=  (0xFUL << 8);
GPIOB->CRH &= ~(0xFUL << 12);
GPIOB->CRH |=  (0xFUL << 12);

/* 3. I2C2 config */
I2C2->CR2 = 36;               // FREQ = PCLK1 MHz
I2C2->CCR = 0x0B4;       // 100kHz, CCR=180
I2C2->TRISE = 37;                // max rise time = 37
I2C2->CR1 = 1;                  // PE=1, enable

}


int main(void)
{
    i2c2_init();
    for (;;) {
        volatile error_chain_t rc = i2c2_write(0x68, 0x00, 0x01);
        (void)rc;
        for (volatile int d = 0; d < 500000; d++) {
        }
    }
}
