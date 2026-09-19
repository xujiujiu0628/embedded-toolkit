/* f103-wwdg — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: 窗口看门狗配置 (计数上限/窗口/分频); 纯函数 wwdg_refresh_allowed
 *       供 host 断言窗口语义。
 * ref.json anchor: peripherals.WWDG (CR bits 0:6=T 7=WDGA; CFR 0:6=W
 *                  7:8=WDGTB 9=EWI; SR bit0=EWI)。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): host 断言加深 — 窗口边界 + 7 位宽度
 *          防御 + 超时模型已知答案 (GAP-D-4 分频系数注记)。
 */
#include "f103_regs.h"

/* 窗口语义 (纯函数, host 可测): 7 位计数自 0x7F 递减, 低于 0x3F 即复位;
 * 喂狗仅允许在 0x3F < t < W 的窗口内 (早喂即复位)。
 * t/w 均为 7 位 (ref.json WWDG.CR bits 0:6)。 */
static int wwdg_refresh_allowed(uint32_t t, uint32_t w)
{
    if (((t | w) & ~0x7Fu) != 0u) {      /* 二期防御: T/W 均 7 位
                                            (ref WWDG.CR/CFR bits 0:6) */
        return 0;
    }
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

/* WWDG 超时模型 (host-only): 计数 0x7F→0x3F 共 64 档, 每档 4096*2^WDGTB
 * 个 PCLK (RM 语义 — 分频系数 ref.json 未登记, GAP-D-4); WDGTB 为 2 位
 * 域 (ref WWDG.CFR bits 7:8) → >3 拒绝。手算: 64*4096=262144 PCLK,
 * WDGTB=1 → 524288 PCLK / 72MHz = 7281.7µs → 截断 7281 */
static uint32_t wwdg_timeout_us(uint32_t wdgtb, uint32_t pclk_hz)
{
    if (wdgtb > 3u || pclk_hz == 0u) {
        return 0u;
    }
    return ((0x40u * 0x1000u) << wdgtb) * 1000000ULL / pclk_hz;
}

int main(void)
{
    /* 窗口语义断言 (期望值按 0x3F < t < W 定义演算) */
    CHECK(wwdg_refresh_allowed(0x46u, 0x50u) == 1);  /* 窗口内 → 允许 */
    CHECK(wwdg_refresh_allowed(0x60u, 0x50u) == 0);  /* 高于窗口 → 过早喂, 禁止 */
    CHECK(wwdg_refresh_allowed(0x3Fu, 0x50u) == 0);  /* 已达下限 → 复位态 */
    /* 组1 窗口边界: 最小合法窗口 0x41; t==w 严禁域 (严格小于);
     * 上满档 0x7F 窗口 */
    CHECK(wwdg_refresh_allowed(0x40u, 0x41u) == 1);
    CHECK(wwdg_refresh_allowed(0x7Fu, 0x7Fu) == 0);
    CHECK(wwdg_refresh_allowed(0x7Eu, 0x7Fu) == 1);
    /* 组2 非法输入防御 (二期新增): T/W 超 7 位宽度 → 拒绝 */
    CHECK(wwdg_refresh_allowed(0x80u, 0x50u) == 0);
    CHECK(wwdg_refresh_allowed(0x46u, 0x80u) == 0);
    /* 组3 超时模型已知答案 (手算见函数注): WDGTB=0/1/3 → 3640/7281/
     * 29127 µs (PCLK=72MHz); 防御: WDGTB 超宽/零时钟 → 0 */
    CHECK(wwdg_timeout_us(0, 72000000u) == 3640u);
    CHECK(wwdg_timeout_us(1, 72000000u) == 7281u);
    CHECK(wwdg_timeout_us(3, 72000000u) == 29127u);
    CHECK(wwdg_timeout_us(4, 72000000u) == 0u);
    CHECK(wwdg_timeout_us(1, 0u) == 0u);
    /* 配置序列断言 */
    wwdg_config();
    CHECK(f103_mock_WWDG.CR  == (0x7Fu | 0x80u));
    CHECK(f103_mock_WWDG.CFR == (0x50u | (1u << 7)));
    CHECK(f103_mock_RCC.APB1ENR & RCC_APB1ENR_WWDGEN);
    /* 组4 刷新写值位型: 窗口内刷新 (与 main 场景同参 0x46+WDGA) */
    WWDG->CR = 0x46u | (1UL << 7);
    CHECK(f103_mock_WWDG.CR == 0xC6u);
    /* 组5 WDGTB 满档变体位型: CFR = W=0x50 | WDGTB=11 (bits 7:8) */
    WWDG->CFR = (0x50u << 0) | (3u << 7);
    CHECK(f103_mock_WWDG.CFR == (0x50u | (3u << 7)));
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
