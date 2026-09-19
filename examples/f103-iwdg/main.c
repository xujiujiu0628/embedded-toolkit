/* f103-iwdg — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: 独立看门狗 100ms 超时配置; 纯函数 iwdg_timeout_us 供 host 断言。
 * ref.json anchor: peripherals.IWDG (KR/PR/RLR/SR 偏移与位宽)。
 * GAP-D-4: KR 魔数序列 0x5555/0xAAAA/0xCCCC 与 LSI=40kHz 为 ST 架构常量,
 *          ref.json 未登记 (PR/RLR 位宽与 SR 位名已锚定)。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): host 断言加深 — tick/反解边界 + 非法
 *          PR 防御 (0 哨兵, 规避除零)。
 */
#include "f103_regs.h"

/* 超时换算 (纯函数, host 可测):
 * tick = (4 << PR) / 40000 s  (LSI 40kHz, 分频 4..256 — GAP-D-4)
 * tick_us(PR) = (4 << PR) * 25 ; timeout_us(PR, RL) = RL * tick_us(PR) */
static uint32_t iwdg_tick_us(uint32_t pr)
{
    if (pr > 7u) {                       /* 二期防御: ref.json IWDG.PR
                                            bits 0:2 — 越宽返回 0 哨兵 */
        return 0u;
    }
    return (4UL << pr) * 25UL;
}

static uint32_t iwdg_timeout_us(uint32_t pr, uint32_t rl)
{
    return rl * iwdg_tick_us(pr);
}

static uint32_t iwdg_rl_for_us(uint32_t pr, uint32_t want_us)
{
    uint32_t tick = iwdg_tick_us(pr);
    if (tick == 0u) {                    /* 二期防御: 非法 PR → 0 哨兵
                                            (同时规避除零) */
        return 0u;
    }
    return want_us / tick;
}

/* 配置序列 — target 写真寄存器 / host(F103_MOCK_REGS) 写重定向结构, 两态共用 */
static void iwdg_config_100ms(void)
{
    /* 目标 100ms: PR=2 → tick 400µs, RL 由换算函数推导 = 250 */
    uint32_t rl = iwdg_rl_for_us(2u, 100000u);
    IWDG->KR  = 0x5555;                  /* 解锁 PR/RLR 写入 (GAP-D-4) */
    IWDG->PR  = 2;                       /* ref.json IWDG.PR bits 0:2 */
    IWDG->RLR = rl;                      /* ref.json IWDG.RLR bits 0:11 */
    IWDG->KR  = 0xAAAA;                  /* 喂狗 (reload) */
    IWDG->KR  = 0xCCCC;                  /* 启动 */
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    uint32_t rl = iwdg_rl_for_us(2u, 100000u);
    iwdg_config_100ms();
    if (iwdg_timeout_us(2u, rl) != 100000u) {
        for (;;) {                       /* 配置自洽校验失败 (理论不可达) */
        }
    }
    for (;;) {
        /* 最小使用场景: 主循环周期喂狗 (真机须短于 100ms) */
        IWDG->KR = 0xAAAA;
        for (volatile int d = 0; d < 10000; d++) {
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
    /* 1) 纯换算断言 (期望值由公式手工演算, 不与实现共享代码) */
    CHECK(iwdg_timeout_us(0, 4095) == 409500u);   /* 最小分频, RL 满档 */
    CHECK(iwdg_timeout_us(6, 4095) == 26208000u); /* 最大≈26.2s */
    /* 组1 tick 边界 (手算: (4<<PR)*25): PR=0 → 100µs, PR=7 → 12800µs;
     * 满档超时 4095*12800 = 52416000µs ≈ 52.4s */
    CHECK(iwdg_tick_us(0) == 100u);
    CHECK(iwdg_tick_us(7) == 12800u);
    CHECK(iwdg_timeout_us(7, 4095) == 52416000u);
    /* 组2 反解边界 (手算): 1s@PR=4 (tick 1600µs) → 625;
     * 不足一个 tick 的目标 → 0 */
    CHECK(iwdg_rl_for_us(4, 1000000u) == 625u);
    CHECK(iwdg_rl_for_us(0, 50u) == 0u);
    /* 组3 RL=0 边界: 超时为 0 ( reload 前无计数) */
    CHECK(iwdg_timeout_us(2, 0) == 0u);
    /* 组4 非法输入防御 (二期新增): PR>7 越宽 → 全链 0 哨兵, 且
     * 反解路径不除零 */
    CHECK(iwdg_tick_us(8) == 0u);
    CHECK(iwdg_timeout_us(8, 4095) == 0u);
    CHECK(iwdg_rl_for_us(8, 100000u) == 0u);
    /* 2) 寄存器写序列断言 (KR 只写, mock 断言的是写入动作) */
    iwdg_config_100ms();
    CHECK(f103_mock_IWDG.KR  == 0xCCCCu);
    CHECK(f103_mock_IWDG.PR  == 2u);
    CHECK(f103_mock_IWDG.RLR == 250u);
    CHECK(iwdg_timeout_us(2u, f103_mock_IWDG.RLR) == 100000u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
