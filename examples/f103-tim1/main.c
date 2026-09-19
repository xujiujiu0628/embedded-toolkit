/* f103-tim1 — T2 手写寄存器级样例 (编译级)。
 * 用途: 高级定时器 10kHz PWM, 互补通道使能, 死区 + 刹车输入配置,
 *       最后 MOE 主输出使能 (高级定时器专属)。
 * ref.json anchor: peripherals.TIM1 (CCMR1_Output/CCER/BDTR/RCR/EGR 位名),
 *                  _relationships.TIM1.pins (CH1=A8), RCC.APB2ENR bit11。
 * GAP-D-4: CH1N/BKIN 引脚 (PB13/PB12 默认映射) ref.json 未登记, 本样例
 *          只配 CH1 的 GPIO, 互补/刹车引脚需另行按板线确认。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): 新增 host mock — 分频/死区换算已知答案
 *          + 配置序列位型断言。
 */
#include "f103_regs.h"

static void tim1_complementary_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN | RCC_APB2ENR_IOPAEN;
    __DSB();
    /* CH1=PA8 复用推挽 50MHz (ref.json _relationships.TIM1.pins CH1=A8,
     * CRL 每 pin 4 位 → PA8 在 CRH bits 0:3) */
    GPIOA->CRH &= ~(0xFUL << 0);
    GPIOA->CRH |=  (0xBUL << 0);

    TIM1->PSC  = 71;                      /* 72MHz/72 = 1MHz */
    TIM1->ARR  = 99;                      /* → 10kHz */
    TIM1->CCR1 = 50;                      /* 50% */
    TIM1->RCR  = 0;                       /* ref.json TIM1.RCR bits 0:7 */
    /* CCMR1_Output: OC1M=110 (PWM1) bits 4:6, OC1PE bit3
     * (ref.json TIM1.CCMR1_Output bits) */
    TIM1->CCMR1 = (6UL << 4) | (1UL << 3);
    /* CCER: CC1E@0 CC1P@1 CC1NE@2 CC1NP@3 — 互补对使能 */
    TIM1->CCER = (1UL << 0) | (1UL << 2);
    /* BDTR: DTG@0:7 死区=32*TDTS, BKE@12 刹车使能, MOE@15 主输出 */
    TIM1->BDTR = (32UL << 0) | (1UL << 12) | (1UL << 15);
    TIM1->EGR  = (1UL << 0);              /* UG 生成更新事件重载 */
    TIM1->CR1  = (1UL << 7) | (1UL << 0); /* ARPE + CEN */
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    tim1_complementary_init();
    for (;;) {
        __WFI();                          /* 硬件自主输出 */
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

/* 推导辅助 (host-only): f = clk/((PSC+1)*(ARR+1)) — 期望常数均为手算 */
static uint32_t tim_output_hz(uint32_t tim_clk_hz, uint32_t psc,
                              uint32_t arr)
{
    return tim_clk_hz / ((psc + 1u) * (arr + 1u));
}

/* 推导辅助 (host-only): 死区 DT = DTG * t_DTS (DTG<128 线性段, RM 语义
 * — DTG 编码 ref.json 未登记, GAP-D-4); CKD=00 → t_DTS=1/tim_clk。
 * DTG≥128 属双段编码域, 本样例只覆盖线性段 → 0 哨兵 */
static uint32_t tim1_deadtime_ns(uint32_t dtg, uint32_t tim_clk_hz)
{
    if (dtg > 127u || tim_clk_hz == 0u) {
        return 0u;
    }
    return (uint32_t)((dtg * 1000000000ULL) / tim_clk_hz);
}

int main(void)
{
    /* 组1 分频已知答案 (手算): 72M/(71+1)/(99+1) = 72M/7200 = 10kHz;
     * 边界: PSC=0 + ARR 满档 → 72M/65536 = 1098 (截断) */
    CHECK(tim_output_hz(72000000u, 71u, 99u) == 10000u);
    CHECK(tim_output_hz(72000000u, 0u, 0xFFFFu) == 1098u);
    /* 组2 死区换算已知答案 (手算): DTG=32 → 32e9/72e6 = 444ns 截断;
     * DTG=127 → 1763ns */
    CHECK(tim1_deadtime_ns(32u, 72000000u) == 444u);
    CHECK(tim1_deadtime_ns(127u, 72000000u) == 1763u);
    /* 组3 非法输入防御: DTG≥128 / 零时钟 → 0 哨兵 */
    CHECK(tim1_deadtime_ns(128u, 72000000u) == 0u);
    CHECK(tim1_deadtime_ns(32u, 0u) == 0u);
    /* 组4 配置序列位型 (mock 终态, 逐项手算):
     * CRH 低 4 位=0xB (PA8 复用推挽 50MHz); CCMR1=(6<<4)|(1<<3)=0x68;
     * CCER=CC1E(0)|CC1NE(2)=0x5; BDTR=DTG(0:7)=32|BKE(12)|MOE(15)
     * =0x9020; EGR=UG(0)=1 (mock 保留写值); CR1=ARPE(7)|CEN(0)=0x81 */
    tim1_complementary_init();
    CHECK(f103_mock_RCC.APB2ENR & RCC_APB2ENR_TIM1EN);
    CHECK(f103_mock_GPIOA.CRH == 0xBu);
    CHECK(f103_mock_TIM1.PSC == 71u && f103_mock_TIM1.ARR == 99u);
    CHECK(f103_mock_TIM1.CCR1 == 50u);
    CHECK(f103_mock_TIM1.RCR == 0u);
    CHECK(f103_mock_TIM1.CCMR1 == 0x68u);
    CHECK(f103_mock_TIM1.CCER == 0x5u);
    CHECK(f103_mock_TIM1.BDTR == 0x9020u);
    CHECK(f103_mock_TIM1.EGR == 1u);
    CHECK(f103_mock_TIM1.CR1 == 0x81u);
    /* 组5 序列↔换算联动: mock 终态回代分频函数仍得目标频率 */
    CHECK(tim_output_hz(72000000u, f103_mock_TIM1.PSC,
                        f103_mock_TIM1.ARR) == 10000u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
