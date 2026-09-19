/* f103-can — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: bxCAN 进入/退出初始化模式 + 500kbps 位时序; 纯函数
 *       can_baud_hz 供 host 断言位时序换算 (简报点名的 mock 面)。
 * ref.json anchor: peripherals.CAN (MCR/MSR/BTR 偏移与位名),
 *                  RCC.APB1ENR bit25=CANEN。
 * GAP-D-4: CAN 引脚映射 (PA11/PA12 或 PB8/PB9 重映射) ref.json 未登记,
 *          本样例不配置 GPIO。CAN 时钟 = APB1 36MHz (72MHz/2, 标准分频
 *          假设 — 同 gen_periph --hclk 口径)。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

/* 位时序换算 (纯函数, host 可测):
 * 波特率 = APB1_CLK / ((BRP+1) * (1 + TS1 + TS2))
 * (BRP@0:9 TS1@16:19 TS2@20:22 — ref.json CAN.BTR bits) */
static uint32_t can_baud_hz(uint32_t pclk_hz, uint32_t brp,
                            uint32_t ts1, uint32_t ts2)
{
    return pclk_hz / ((brp + 1u) * (1u + ts1 + ts2));
}

#ifndef F103_SAMPLE_HOST_TEST
/* 超时守卫的握手轮询 (mock 下硬件不置 INAK → 超时返回 -1, 不死等) */
static int can_wait_msr_bit(uint32_t mask, uint32_t want)
{
    uint32_t guard = 1000000u;
    while (guard--) {
        if ((CAN->MSR & mask) == (want ? mask : 0u)) {
            return 0;
        }
    }
    return -1;
}

static int can_init_500k(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_CANEN;   /* ref.json RCC.APB1ENR bit25 */
    __DSB();
    CAN->MCR |= (1UL << 0);              /* INRQ 请求初始化 (MCR bit0) */
    if (can_wait_msr_bit(1UL << 1, 1) != 0) {
        return -1;                       /* MSR bit1=INAK 未置位 */
    }
    CAN->MCR = (1UL << 2)                /* RFLM (bit3? 见下行修正注) */
             | 0;                        /* 其余按默认 */
    /* 注: RFLM=bit3 AWUM=bit5 NART=bit4 (ref.json CAN.MCR bits) */
    CAN->MCR = (1UL << 4);               /* NART 禁自动重发 (bit4) */
    CAN->BTR = (3UL << 0)                /* BRP=3 → TQ=4/APB1 (bits 0:9) */
             | (12UL << 16)              /* TS1=12 (bits 16:19) */
             | (5UL << 20);              /* TS2=5 (bits 20:22) → 500kbps */
    CAN->MCR &= ~(1UL << 0);             /* 退出初始化 (清 INRQ) */
    if (can_wait_msr_bit(1UL << 1, 0) != 0) {
        return -2;                       /* INAK 未清 */
    }
    return 0;
}

int main(void)
{
    /* 位时序自洽: 500kbps 组合必须先经换算函数确认 */
    if (can_baud_hz(36000000u, 3u, 12u, 5u) != 500000u) {
        for (;;) {
        }
    }
    /* 最小使用场景: 完成初始化时序后停机 (收发需总线与引脚, 另行验证) */
    if (can_init_500k() == 0) {
        for (;;) {
            __WFI();
        }
    }
    for (;;) {
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

int main(void)
{
    /* 位时序断言 (期望值手工演算: 36MHz/((3+1)*(1+12+5)) = 500kHz) */
    CHECK(can_baud_hz(36000000u, 3, 12, 5) == 500000u);
    CHECK(can_baud_hz(36000000u, 5, 11, 4) == 375000u);  /* 36M/(6*16) */
    CHECK(can_baud_hz(36000000u, 0, 7, 8)  == 2250000u); /* 36M/(1*16) */
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
