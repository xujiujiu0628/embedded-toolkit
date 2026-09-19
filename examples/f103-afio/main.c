/* f103-afio — T2 手写寄存器级样例 (编译级)。
 * 用途: AFIO 三件事演示 — EXTI 线到端口的路由 (EXTICR)、外设重映射
 *       (MAPR)、SWJ 调试口配置 (MAPR bits 24:26, 写只读读)。
 * ref.json anchor: peripherals.AFIO (MAPR/EXTICR1/EVCR/MAPR2 位名),
 *                  RCC.APB2ENR bit0=AFIOEN。
 * 硬件验收: 未做（编译级样例）
 * mock 二期 (WB-20260920-02): 新增 host mock — 掩码清洗/路由编码/
 *          重映射值计算断言。
 */
#include "f103_regs.h"

static void afio_demo(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_AFIOEN | RCC_APB2ENR_IOPAEN;
    __DSB();
    /* EXTI0 路由到 PA0: EXTICR1 bits 0:3 = 0000 → PA
     * (ref.json AFIO.EXTICR1 bits 0:3=EXTI0) */
    AFIO->EXTICR1 &= ~(0xFUL << 0);
    /* TIM2 CH1/CH2 不重映射 (MAPR bits 8:9=TIM2_REMAP 保持 00):
     * ref.json AFIO.MAPR bits 8:9 — 保持默认 PA0/PA1 */
    AFIO->MAPR &= ~((3UL << 8) | (3UL << 10));   /* TIM2/TIM3_REMAP=00 */
    /* SWJ_CFG=000 完整 SWJ (JTAG+SWD): bits 24:26 写只读读
     * (ref.json AFIO.MAPR bits 24:26=SWJ_CFG) */
    AFIO->MAPR &= ~(7UL << 24);
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    afio_demo();
    for (;;) {
        __WFI();
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

/* 推导辅助 (host-only): EXTI0 线到端口的 EXTICR1 bits 0:3 编码
 * (PA=0..PG=6, RM 语义 GAP-D-4) — >7 超端口数 → 保留值 0xF 哨兵 */
static uint32_t afio_exticr_encode(uint32_t port)
{
    return port > 7u ? 0xFu : port;
}

/* 推导辅助 (host-only): TIM2_REMAP (MAPR bits 8:9) 模式值计算 —
 * 00=无重映射 (PA0/PA1 默认), 11=完全重映射 */
static uint32_t afio_tim2_remap_mapr(uint32_t mode)
{
    return (mode & 3u) << 8;
}

int main(void)
{
    /* 预置脏值: 验证掩码清洗"只清目标位、其余保留" */
    f103_mock_AFIO.EXTICR1 = 0x33333333u;
    f103_mock_AFIO.MAPR = 0xFFFFFFFFu;
    /* 组1 EXTICR1 掩码清洗 (手算): 低 4 位 (EXTI0 路由域) 清零,
     * 其余保留 → 0x33333330 */
    afio_demo();
    CHECK(f103_mock_RCC.APB2ENR & RCC_APB2ENR_AFIOEN);
    CHECK(f103_mock_AFIO.EXTICR1 == 0x33333330u);
    /* 组2 MAPR 双重掩码 (手算): 清 TIM2/TIM3_REMAP (bits 8:11) 与
     * SWJ_CFG (bits 24:26) → 0xFFFFF0FF & 0xF8FFFFFF = 0xF8FFF0FF */
    CHECK(f103_mock_AFIO.MAPR == 0xF8FFF0FFu);
    /* 组3 路由编码已知答案 (手算): EXTI0←PA0/PB0/PC0 → 0/1/2 */
    CHECK(afio_exticr_encode(0u) == 0x0u);
    CHECK(afio_exticr_encode(1u) == 0x1u);
    CHECK(afio_exticr_encode(2u) == 0x2u);
    /* 组4 重映射值计算 (手算): mode=0 → bits 8:9=00 (与组2 终态
     * 一致); mode=3 → 3<<8 */
    CHECK((afio_tim2_remap_mapr(0u) & (3u << 8)) == 0u);
    CHECK(afio_tim2_remap_mapr(3u) == (3u << 8));
    /* 组5 非法输入防御: 端口号 >7 → 保留值 0xF 哨兵 */
    CHECK(afio_exticr_encode(8u) == 0xFu);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
