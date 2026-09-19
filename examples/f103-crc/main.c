/* f103-crc — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: CRC 单元复位后逐字喂数, 读 CRC 结果。
 * ref.json anchor: peripherals.CRC (DR@0x00 0:31, IDR@0x04 0:7, CR@0x08
 *                  bit0=RESET); RCC.AHBENR bit6=CRCEN。
 * GAP-D-4: 多项式 0x4C11DB7 与字序为 ST 固定语义, ref.json 未登记,
 *          本样例不做参考实现对照 — mock 只断言寄存器写序列。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

/* 配置/喂数序列 — target 写真寄存器 / host(F103_MOCK_REGS) 写重定向结构, 两态共用 */
static void crc_init(void)
{
    RCC->AHBENR |= RCC_AHBENR_CRCEN;     /* ref.json RCC.AHBENR bit6=CRCEN */
    __DSB();
    CRC->CR = (1UL << 0);                /* RESET 位 (ref.json CRC.CR bit0) */
}

static uint32_t crc_feed(const uint32_t *words, uint32_t n)
{
    for (uint32_t i = 0; i < n; i++) {
        CRC->DR = words[i];              /* ref.json CRC.DR bits 0:31 */
    }
    return CRC->DR;
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    static const uint32_t payload[4] = {0x12345678u, 0x9ABCDEF0u,
                                        0x0F1E2D3Cu, 0x4B5A6978u};
    crc_init();
    for (;;) {
        /* 最小使用场景: 复位 → 喂 4 字 → 读结果 */
        CRC->CR = (1UL << 0);
        (void)crc_feed(payload, 4);
        __WFI();
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

int main(void)
{
    static const uint32_t payload[4] = {0x12345678u, 0x9ABCDEF0u,
                                        0x0F1E2D3Cu, 0x4B5A6978u};
    crc_init();
    CHECK(f103_mock_RCC.AHBENR & RCC_AHBENR_CRCEN);
    CHECK(f103_mock_CRC.CR == 1u);            /* 复位脉冲已发 */
    (void)crc_feed(payload, 4);
    CHECK(f103_mock_CRC.DR == payload[3]);    /* 最后一次写入的字 */
    CRC->IDR = 0xA5u;                         /* ref.json CRC.IDR bits 0:7 */
    CHECK(f103_mock_CRC.IDR == 0xA5u);
    CRC->CR = (1UL << 0);                     /* 再复位 */
    CHECK(f103_mock_CRC.CR == 1u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
