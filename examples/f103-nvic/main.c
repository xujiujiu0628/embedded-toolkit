/* f103-nvic — T2 手写寄存器级样例 (编译级)。
 * 用途: NVIC 使能/禁用/优先级写入演示, 以 TIM2 更新中断 (IRQ 28) 为例。
 * ref.json anchor: peripherals.NVIC (ISER@0xE000E100 + ICER/ISPR/ICPR/
 *                  IABR/IP — @F-179 P1 入册, 原 GAP-D-1 已闭合);
 *                  TIM2 irq=28 来自
 *                  ref.json _relationships.TIM2.irq。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): 新增 host mock — IRQ 槽位算术/优先级
 *          字节编码/ISER-ICER 留痕断言。
 */
#include "f103_regs.h"

static void nvic_tim2_demo(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;   /* 中断源时钟 */
    __DSB();
    NVIC->IP[28] = 0x40u;                 /* 抢占优先级 1 (IP 按字节宽) */
    NVIC->ISER[0] = (1UL << 28);          /* 使能 TIM2 IRQ (写 1 置位) */
    NVIC->ICER[0] = (1UL << 28);          /* 禁用 (写 1 清位) */
    NVIC->ISER[0] = (1UL << 28);          /* 再使能 */
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    nvic_tim2_demo();
    for (;;) {
        __WFI();                          /* TIM2 未配置即无中断, 演示宿主 */
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

/* 推导辅助 (host-only): NVIC 槽位算术 — ISER 字 = IRQ/32, 位 =
 * 1<<(IRQ%32) (Cortex-M3 架构); 期望常数均为手算 */
static uint32_t nvic_iser_word(uint32_t irq) { return irq / 32u; }
static uint32_t nvic_iser_bit(uint32_t irq)  { return 1u << (irq % 32u); }

/* 推导辅助 (host-only): F103 优先级域 = IP bits 7:4 (4 位) —
 * p>15 超域 → 0 哨兵 */
static uint32_t nvic_ip_encode(uint32_t p)
{
    return p > 15u ? 0u : (p << 4);
}

int main(void)
{
    /* 组1 IRQ 槽位算术 (手算): TIM2 IRQ=28 (ref _relationships) →
     * 字 0 位 28 → 0x10000000 */
    nvic_tim2_demo();
    CHECK(f103_mock_RCC.APB1ENR & RCC_APB1ENR_TIM2EN);
    CHECK(f103_mock_NVIC.ISER[0] == 0x10000000u);
    /* 组2 优先级字节编码: IP[28] 写入值 0x40 → bits 7:4 = 0x4。
     * 勘误见报告: 一期注释称"抢占优先级 1"与编码不符 (1 应为
     * 0x10); 断言以实际写入值为准, 语义勘误不改初始化序列 */
    CHECK(f103_mock_NVIC.IP[28] == 0x40u);
    /* 组3 ICER 写值留痕: demo 中间禁用过一次 → ICER[0] 同位型
     * (ISER/ICER 分寄存器, 写入动作互不覆盖) */
    CHECK(f103_mock_NVIC.ICER[0] == 0x10000000u);
    /* 组4 槽位算术已知答案 (手算): IRQ 55 (TIM7, GAP-D-3 未登记,
     * 架构常量) → 字 1 位 23; IRQ 28 → 字 0 位 28 */
    CHECK(nvic_iser_word(55u) == 1u && nvic_iser_bit(55u) == (1u << 23));
    CHECK(nvic_iser_word(28u) == 0u && nvic_iser_bit(28u) == (1u << 28));
    /* 组5 优先级域宽度边界+防御 (手算): 1→0x10, 15→0xF0 满档,
     * 16 超域 → 0 哨兵 */
    CHECK(nvic_ip_encode(1u) == 0x10u);
    CHECK(nvic_ip_encode(15u) == 0xF0u);
    CHECK(nvic_ip_encode(16u) == 0u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
