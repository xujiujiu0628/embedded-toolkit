/* f103-wwdg — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: 窗口看门狗配置 (计数上限/窗口/分频); 纯函数 wwdg_refresh_allowed
 *       供 host 断言窗口语义。
 * ref.json anchor: peripherals.WWDG (CR bits 0:6=T 7=WDGA; CFR 0:6=W
 *                  7:8=WDGTB 9=EWI; SR bit0=EWI)。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

/* 窗口语义 (纯函数, host 可测): 7 位计数自 0x7F 递减, 低于 0x3F 即复位;
 * 喂狗仅允许在 0x3F < t < W 的窗口内 (早喂即复位)。
 * t/w 均为 7 位 (ref.json WWDG.CR bits 0:6)。 */
static int wwdg_refresh_allowed(uint32_t t, uint32_t w)
{
    return (t > 0x3Fu) && (t < w);
}

/* 配置序列 — target 写真寄存器 / host(F103_MOCK_REGS) 写重定向结构, 两态共用 */
static void wwdg_config(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_WWDGEN;  /* ref.json RCC.APB1ENR bit11=WWDGEN */
    __DSB();
    WWDG->CFR = (0x50UL << 0)            /* W=0x50 窗口 (bits 0:6) */
              | (1UL << 7);              /* WDGTB=1 (PCLK/8, bits 7:8) */
    WWDG->SR  = 0;                       /* 清 EWI (ref.json WWDG.SR bit0) */
    WWDG->CR  = 0x7FUL | (1UL << 7);     /* T=0x7F + WDGA 启动 */
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    wwdg_config();
    for (;;) {
        /* 最小使用场景: 计数降到窗口内刷新 (t=0x46 < W=0x50) */
        if (wwdg_refresh_allowed(0x46u, 0x50u)) {
            WWDG->CR = 0x46u | (1UL << 7);
        }
        for (volatile int d = 0; d < 1000; d++) {
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
    /* 窗口语义断言 (期望值按 0x3F < t < W 定义演算) */
    CHECK(wwdg_refresh_allowed(0x46u, 0x50u) == 1);  /* 窗口内 → 允许 */
    CHECK(wwdg_refresh_allowed(0x60u, 0x50u) == 0);  /* 高于窗口 → 过早喂, 禁止 */
    CHECK(wwdg_refresh_allowed(0x3Fu, 0x50u) == 0);  /* 已达下限 → 复位态 */
    /* 配置序列断言 */
    wwdg_config();
    CHECK(f103_mock_WWDG.CR  == (0x7Fu | 0x80u));
    CHECK(f103_mock_WWDG.CFR == (0x50u | (1u << 7)));
    CHECK(f103_mock_RCC.APB1ENR & RCC_APB1ENR_WWDGEN);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
