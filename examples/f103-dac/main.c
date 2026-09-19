/* f103-dac — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: DAC 通道 1 软件触发输出; 纯函数 dac_mv_to_code 供 host 断言。
 * ref.json anchor: peripherals.DAC (CR/SWTRIGR/DHR12R1/DOR1 位名),
 *                  RCC.APB1ENR bit29=DACEN; DAC available_on_c8=false。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): host 断言加深 — 边界/防御 + clamp 进序列。
 */
#include "f103_regs.h"

/* mv→12bit 码值 (Vref=3.3V, 纯函数 host 可测)。
 * 二期防御: 超 12 位满档 clamp 4095 — 先判后乘, 合法输入行为不变 */
static uint32_t dac_mv_to_code(uint32_t mv)
{
    if (mv > 3300u) {
        return 4095u;
    }
    return mv * 4095u / 3300u;
}

/* 配置/写值序列 — target 写真寄存器 / host(F103_MOCK_REGS) 写重定向结构, 两态共用 */
static void dac1_init(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_DACEN;   /* ref.json RCC.APB1ENR bit29 */
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;
    __DSB();
    GPIOA->CRL &= ~(0xFUL << 16);        /* PA4 模拟输入 CNF=00 MODE=00 */
    DAC->CR = (1UL << 0)                 /* EN1 (ref.json DAC.CR bit0) */
            | (1UL << 2);                /* TEN1 (bit2, 使能触发) */
    DAC->CR |= (1UL << 0);
}

static void dac1_write_mv(uint32_t mv)
{
    DAC->DHR12R1 = dac_mv_to_code(mv);   /* ref.json DAC.DHR12R1 bits 0:11 */
    DAC->SWTRIGR = (1UL << 0);           /* SWTRIG1 软件触发 (bit0) */
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    dac1_init();
    for (;;) {
        /* 最小使用场景: 锯齿输出 (0 → 3300mV 步进) */
        for (uint32_t mv = 0; mv <= 3300u; mv += 100u) {
            dac1_write_mv(mv);
            for (volatile int d = 0; d < 1000; d++) {
            }
        }
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

int main(void)
{
    /* 组1 换算断言 (期望值手工演算) + 整除截断边界 */
    CHECK(dac_mv_to_code(3300) == 4095u);
    CHECK(dac_mv_to_code(0)    == 0u);
    CHECK(dac_mv_to_code(1650) == 2047u);   /* 1650*4095/3300 整除截断 */
    CHECK(dac_mv_to_code(1)    == 1u);      /* 4095/3300=1.24 → 1 */
    CHECK(dac_mv_to_code(3299) == 4093u);   /* 13509405/3300=4093.8 → 4093 */
    /* 组2 满档边界: ref.json DAC.DHR12R1 bits 0:11 上满档 */
    CHECK(dac_mv_to_code(3300) == 4095u);
    /* 组3 非法输入防御 (二期新增): 超量程 clamp 4095, 含乘法溢出
     * 输入 (先判后乘, 不回绕) */
    CHECK(dac_mv_to_code(5000) == 4095u);
    CHECK(dac_mv_to_code(0xFFFFFFFFu) == 4095u);
    /* 组4 init 序列断言 */
    dac1_init();
    CHECK(f103_mock_RCC.APB1ENR & RCC_APB1ENR_DACEN);
    CHECK(f103_mock_RCC.APB2ENR & RCC_APB2ENR_IOPAEN);
    CHECK(f103_mock_DAC.CR == ((1u << 0) | (1u << 2)));
    /* 组5 write 序列 + clamp 联动 (防御经写值路径生效) */
    dac1_write_mv(1650);
    CHECK(f103_mock_DAC.DHR12R1 == 2047u);
    CHECK(f103_mock_DAC.SWTRIGR == 1u);
    dac1_write_mv(5000);
    CHECK(f103_mock_DAC.DHR12R1 == 4095u);
    dac1_write_mv(0);
    CHECK(f103_mock_DAC.DHR12R1 == 0u);
    CHECK(f103_mock_DAC.SWTRIGR == 1u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
