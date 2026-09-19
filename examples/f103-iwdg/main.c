/* f103-iwdg — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: 独立看门狗 100ms 超时配置; 纯函数 iwdg_timeout_us 供 host 断言。
 * ref.json anchor: peripherals.IWDG (KR/PR/RLR/SR 偏移与位宽)。
 * GAP-D-4: KR 魔数序列 0x5555/0xAAAA/0xCCCC 与 LSI=40kHz 为 ST 架构常量,
 *          ref.json 未登记 (PR/RLR 位宽与 SR 位名已锚定)。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

/* 超时换算 (纯函数, host 可测):
 * tick = (4 << PR) / 40000 s  (LSI 40kHz, 分频 4..256 — GAP-D-4)
 * tick_us(PR) = (4 << PR) * 25 ; timeout_us(PR, RL) = RL * tick_us(PR) */
static uint32_t iwdg_tick_us(uint32_t pr)
{
    return (4UL << pr) * 25UL;
}

static uint32_t iwdg_timeout_us(uint32_t pr, uint32_t rl)
{
    return rl * iwdg_tick_us(pr);
}

static uint32_t iwdg_rl_for_us(uint32_t pr, uint32_t want_us)
{
    return want_us / iwdg_tick_us(pr);
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
    CHECK(iwdg_timeout_us(6, 4095) == 26208000u); /* 最大分频 ≈26.2s */
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
