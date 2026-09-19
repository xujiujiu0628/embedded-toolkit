/* f103-exti — T2 手写寄存器级样例 (编译级)。
 * 用途: PA0 上升沿触发 EXTI0 中断, ISR 内清挂起标志。
 * ref.json anchor: peripherals.EXTI (IMR/RTSR/PR 位名), peripherals.AFIO
 *                  (EXTICR1 bits 0:3=EXTI0), peripherals.GPIOA。
 * IRQ 槽位: EXTI0 = 6 — ref.json 无 EXTI 的 IRQ 条目 (GAP-D-3)。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): 新增 host mock — 线选择/触发沿配置值
 *          + 掩码清洗 + ISR 清挂起语义断言。
 */
#include "f103_regs.h"

static volatile uint32_t exti0_hits;

void EXTI0_IRQHandler(void)          /* startup.c weak alias 的强符号覆盖 */
{
    if (EXTI->PR & (1UL << 0)) {     /* ref.json EXTI.PR bit0=PR0 */
        EXTI->PR |= (1UL << 0);      /* 写 1 清除挂起 (rc_w1) */
        exti0_hits++;
    }
}

static void exti0_pa0_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_AFIOEN;
    __DSB();
    GPIOA->CRL &= ~(0xFUL << 0);     /* PA0 CNF=01(浮空输入) MODE=00 */
    GPIOA->CRL |=  (0x4UL << 0);     /* ref.json GPIOA.CRL: 每 pin 4 位 */
    AFIO->EXTICR1 &= ~(0xFUL << 0);  /* ref.json AFIO.EXTICR1 bits 0:3=EXTI0 */
    EXTI->IMR |= (1UL << 0);         /* ref.json EXTI.IMR bit0=MR0 非屏蔽 */
    EXTI->RTSR |= (1UL << 0);        /* ref.json EXTI.RTSR bit0=TR0 上升沿 */
    EXTI->FTSR &= ~(1UL << 0);       /* 禁下降沿 */
    NVIC->ISER[0] = (1UL << 6);      /* EXTI0 IRQ — GAP-D-3 槽位 6 */
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    exti0_pa0_init();
    for (;;) {
        __WFI();                     /* 最小使用场景: 每次沿唤醒 */
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

/* 推导辅助 (host-only): 线掩码 — EXTI 线 0..18 (ref.json EXTI 各
 * 寄存器 bits 0:18); line>18 → 0 哨兵 */
static uint32_t exti_line_mask(uint32_t line)
{
    return line > 18u ? 0u : (1u << line);
}

int main(void)
{
    /* 预置脏值: 验证 GPIO/AFIO/EXTI 掩码清洗"只清目标位、其余保留" */
    f103_mock_GPIOA.CRL = 0xFFFFFFFFu;
    f103_mock_AFIO.EXTICR1 = 0x33333333u;
    f103_mock_EXTI.FTSR = 0xFFFFFFFFu;
    /* 组1 触发沿配置值 (手算): RTSR bit0=1 上升沿使能;
     * FTSR bit0 清零 → 其余位保留 = 0xFFFFFFFE */
    exti0_pa0_init();
    CHECK(f103_mock_EXTI.RTSR == 1u);
    CHECK(f103_mock_EXTI.FTSR == 0xFFFFFFFEu);
    /* 组2 线选择/屏蔽 (手算): IMR bit0=1 (线 0 非屏蔽), EMR 不触碰
     * → 事件屏蔽保持 0 */
    CHECK(f103_mock_EXTI.IMR == 1u);
    CHECK(f103_mock_EXTI.EMR == 0u);
    /* 组3 引脚/路由清洗 (手算): CRL 低 4 位 = 0x4 (PA0 浮空输入
     * CNF=01 MODE=00) 其余保留; EXTICR1 低 4 位 = 0 (路由 PA) */
    CHECK(f103_mock_GPIOA.CRL == 0xFFFFFFF4u);
    CHECK(f103_mock_AFIO.EXTICR1 == 0x33333330u);
    /* 组4 NVIC 槽位 (手算): EXTI0 IRQ=6 [GAP-D-3] → ISER[0]=0x40;
     * 线掩码边界: line=18 合法, line=19 → 0 哨兵 */
    CHECK(f103_mock_NVIC.ISER[0] == 0x40u);
    CHECK(exti_line_mask(18u) == (1u << 18));
    CHECK(exti_line_mask(19u) == 0u);
    /* 组5 ISR 清挂起语义: 预置 PR0 → 命中计 1 (mock 无 rc_w1 语义,
     * PR|=1 保留 1, 写 1 清动作与命中计数分别断言); 无挂起不误计 */
    exti0_hits = 0;
    f103_mock_EXTI.PR = 1u;
    EXTI0_IRQHandler();
    CHECK(exti0_hits == 1u);
    CHECK(f103_mock_EXTI.PR == 1u);
    exti0_hits = 0;
    f103_mock_EXTI.PR = 0u;
    EXTI0_IRQHandler();
    CHECK(exti0_hits == 0u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
