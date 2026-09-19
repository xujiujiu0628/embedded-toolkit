/* f103-dma1 — T2 手写寄存器级样例 (编译级)。
 * 用途: DMA1 通道 1 内存到内存搬运 4 字, 轮询传输完成标志后清位。
 * ref.json anchor: peripherals.DMA1 (ISR/IFR/CCR1..CMAR1 及位名)。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): 新增 host mock — CCR 位型/计数地址/
 *          完成握手/超时防御断言。
 */
#include "f103_regs.h"

static volatile uint32_t dma_src[4] = {0x11111111u, 0x22222222u,
                                       0x33333333u, 0x44444444u};
static volatile uint32_t dma_dst[4];

/* DMA1->CH[0] = CCR1@0x08 (ref.json DMA1.registers.CCR1.offset);
 * CCR 位名: EN@0 TCIE@1 DIR@4 CIRC@5 PINC@6 MINC@7 PSIZE@8:9
 *           MSIZE@10:11 PL@12:13 MEM2MEM@14 (ref.json DMA1.registers.CCR1.bits) */
static void dma1_ch1_mem2mem_start(void)
{
    RCC->AHBENR |= RCC_AHBENR_DMA1EN;      /* ref.json RCC.AHBENR bit0=DMA1EN */
    __DSB();
    DMA1->IFCR = (1UL << 1);               /* CTCIF1@1 — 清残留完成标志 */
    DMA1->CH[0].CPAR  = (uint32_t)dma_src; /* ref.json DMA1.CPAR1 @0x10 */
    DMA1->CH[0].CMAR  = (uint32_t)dma_dst; /* ref.json DMA1.CMAR1 @0x14 */
    DMA1->CH[0].CNDTR = 4;                 /* ref.json DMA1.CNDTR1 @0x0C */
    DMA1->CH[0].CCR = (1UL << 14)          /* MEM2MEM */
                    | (2UL << 10)          /* MSIZE=32bit */
                    | (2UL << 8)           /* PSIZE=32bit */
                    | (1UL << 7)           /* MINC */
                    | (1UL << 4)           /* DIR: 读存储器→写外设址(此处为内存) */
                    | (1UL << 0);          /* EN */
}

static int dma1_ch1_wait_done(void)
{
    uint32_t guard = 1000000u;
    while (guard--) {
        if (DMA1->ISR & (1UL << 1)) {      /* ref.json DMA1.ISR bit1=TCIF1 */
            DMA1->IFCR = (1UL << 1);       /* CTCIF1 写 1 清除 */
            return 0;
        }
    }
    return -1;
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    dma1_ch1_mem2mem_start();
    /* 最小使用场景: 完成后停机 (真机可在断点检查 dma_dst) */
    if (dma1_ch1_wait_done() == 0) {
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
    /* 组1 CCR 位型已知答案 (手算分解, ref DMA1.CCR1 bits):
     * MEM2MEM(14)|MSIZE=10b(10:11)|PSIZE=10b(8:9)|MINC(7)|DIR(4)|EN(0)
     * = 0x4000|0x800|0x200|0x80|0x10|0x1 = 0x4A91 */
    dma1_ch1_mem2mem_start();
    CHECK(f103_mock_RCC.AHBENR & RCC_AHBENR_DMA1EN);
    CHECK(f103_mock_DMA1.CH[0].CCR == 0x4A91u);
    CHECK((f103_mock_DMA1.CH[0].CCR & (1u << 5)) == 0u);  /* CIRC 未置位 */
    /* 组2 传输计数与地址 (ref CNDTR1 bits 0:15, CPAR1/CMAR1 0:31):
     * 计数=4 字; 源/目的首址进 CPAR/CMAR */
    CHECK(f103_mock_DMA1.CH[0].CNDTR == 4u);
    CHECK(f103_mock_DMA1.CH[0].CPAR == (uint32_t)dma_src);
    CHECK(f103_mock_DMA1.CH[0].CMAR == (uint32_t)dma_dst);
    /* 组3 完成握手: start 先写 CTCIF1(bit1) 清残留 → IFCR=0x2;
     * 预置 ISR TCIF1 → wait_done 返回 0 且写 1 清 (mock 保留写值) */
    CHECK(f103_mock_DMA1.IFCR == (1u << 1));
    f103_mock_DMA1.ISR = (1u << 1);       /* 模拟硬件传输完成 */
    CHECK(dma1_ch1_wait_done() == 0);
    CHECK(f103_mock_DMA1.IFCR == (1u << 1));
    /* 组4 超时防御: 无完成标志 → -1 (守卫 1e6 轮, 不死等) */
    f103_mock_DMA1.ISR = 0;
    CHECK(dma1_ch1_wait_done() == -1);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
