/* f103-can — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: bxCAN 进入/退出初始化模式 + 500kbps 位时序; 纯函数
 *       can_baud_hz 供 host 断言位时序换算 (简报点名的 mock 面)。
 * ref.json anchor: peripherals.CAN (MCR/MSR/BTR 偏移与位名),
 *                  RCC.APB1ENR bit25=CANEN。
 * GAP-D-4: CAN 引脚映射 (PA11/PA12 或 PB8/PB9 重映射) ref.json 未登记,
 *          本样例不配置 GPIO。CAN 时钟 = APB1 36MHz (72MHz/2, 标准分频
 *          假设 — 同 gen_periph --hclk 口径)。
 * 硬件验收: ✅ 2026-10-08 真机 PASS (F103C8T6+ST-Link, F-223 修复后复验;
 *          buggy 先红=MCR 停 0x10003/INAK 永不完成); 范围=初始化时序, 详见 README
 * mock 二期 (WB-20260920-02): 四速率已知答案 + 边界/防御 + 序列握手
 *          (序列函数移出 #ifndef, 与其它样例"配置序列两态共用"对齐)。
 */
#include "f103_regs.h"

/* 位时序换算 (纯函数, host 可测):
 * 波特率 = APB1_CLK / ((BRP+1) * (1 + (TS1+1) + (TS2+1)))
 *        = APB1_CLK / ((BRP+1) * (TS1 + TS2 + 3))
 * (BRP@0:9 TS1@16:19 TS2@20:22 — ref.json CAN.BTR bits)
 *
 * F-213: BTR 的 TS1/TS2 字段编码的是 "TQ 数 - 1", 即字段值 N 实际表示
 * N+1 个时间量。位时间 = 1 (同步段) + (TS1+1) + (TS2+1)。原公式按字段值
 * 直算 (1+TS1+TS2), 少算 2 TQ: BRP=3/TS1=12/TS2=5 得 500k 而真机实配
 * 450k。样例此前用 mock 断言把这个错公式固化成了"已知答案", 属自证。 */
static uint32_t can_baud_hz(uint32_t pclk_hz, uint32_t brp,
                            uint32_t ts1, uint32_t ts2)
{
    /* 二期防御: 位域宽度纪律 (ref.json CAN.BTR: BRP bits 0:9,
     * TS1 bits 16:19, TS2 bits 20:22) 与零时钟 — 越界返回 0 哨兵;
     * 合法输入行为逐位不变 */
    if (pclk_hz == 0u || brp > 1023u || ts1 > 15u || ts2 > 7u) {
        return 0u;
    }
    return pclk_hz / ((brp + 1u) * (ts1 + ts2 + 3u));
}

/* 超时守卫的握手轮询 (mock 下硬件不置 INAK → 超时返回 -1, 不死等)。
 * 二期移出 #ifndef: 序列函数两态共用 (host 写重定向结构) */
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
    /* F-223 真机钓出: 原代码等 MSR bit1 并注释为 "bit1=INAK" —— 位号错。
     * ref.json CAN.MSR 与 ST CMSIS (stm32f103xb.h CAN_MSR_INAK_Pos=0)
     * 双源一致: bit0=INAK / bit1=SLAK。真机实测: INRQ 置位后硬件应答
     * 在 INAK(bit0), 码在等的 SLAK(bit1) 永不置位 → 超时退出, 初始化
     * 序列从未走完 (BTR 保持复位值, INRQ 未清)。已订正为 bit0。 */
    if (can_wait_msr_bit(1UL << 0, 1) != 0) {
        return -1;                       /* MSR bit0=INAK 未置位 */
    }
    /* F-213: 以下三处原为整字赋值 (CAN->MCR = ...), 把 INRQ 一并清零——
     * 硬件随即退出初始化模式, 其后写入的 BTR 被静默忽略。配置域寄存器
     * 只能在 INRQ=1 (INAK=1) 期间写, 故一律改用读改写 |=。
     * 位义按 ref.json CAN.MCR bits: TXFP=bit2 RFLM=bit3 NART=bit4
     * AWUM=bit5 (原注释把 bit2 当 RFLM, 位号错)。 */
    CAN->MCR |= (1UL << 3);              /* RFLM 接收 FIFO 溢出覆盖 (bit3) */
    CAN->MCR |= (1UL << 4);              /* NART 禁自动重发 (bit4) */
    CAN->BTR = (3UL << 0)                /* BRP=3 → 4 分频 (bits 0:9) */
             | (10UL << 16)              /* TS1=10 → 11 TQ (bits 16:19) */
             | (5UL << 20);              /* TS2=5 → 6 TQ (bits 20:22) */
    /* 1 + 11 + 6 = 18 TQ/bit × 4 = 72 → 36MHz/72 = 500kbps 真值 */
    CAN->MCR &= ~(1UL << 0);             /* 退出初始化 (清 INRQ) */
    if (can_wait_msr_bit(1UL << 0, 0) != 0) {
        return -2;                       /* INAK 未清 */
    }
    return 0;
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    /* 位时序自洽: 真 500kbps 组合必须先经换算函数确认
     * F-213: BRP=3 (4 分频) 配 18 TQ → TS1+TS2=15, 取 TS1=10/TS2=5 */
    if (can_baud_hz(36000000u, 3u, 10u, 5u) != 500000u) {
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
    /* 组1 四速率已知答案 (20-TQ 家族 TS1=12 TS2=5 → 1+13+6=20 TQ, 手算:
     * 36MHz/((BRP+1)*20), BRP=15/7/3/1 → 分母 320/160/80/40)
     * F-213: 原按 18 TQ 断言 (125k/250k/500k/1M), 那是错公式的产物;
     * 真机 500kbps 需 BRP=3 配 TS1/TS2 编码和 = 17 (如 TS1=10/TS2=5)。 */
    CHECK(can_baud_hz(36000000u, 15, 12, 5) == 112500u);
    CHECK(can_baud_hz(36000000u, 7, 12, 5)  == 225000u);
    CHECK(can_baud_hz(36000000u, 3, 12, 5)  == 450000u);
    CHECK(can_baud_hz(36000000u, 1, 12, 5)  == 900000u);
    /* 组1b 真 500kbps 组合 (BRP=3 → 4 分频, 需 72/4=18 TQ → TS1+TS2=15) */
    CHECK(can_baud_hz(36000000u, 3, 10, 5)  == 500000u);
    CHECK(can_baud_hz(36000000u, 3, 8, 7)   == 500000u);
    /* 组2 边界值 (手算): BRP 满档 1023 (bits 0:9) × TS1=15/TS2=7
     * 满档 → 36M/(1024*25)=1406; 公式退化 3-TQ (同步+TS1+TS2 各 1)
     * → 36M/3=12M (真实帧需 ≥8 TQ 采样点, 此处仅作数值边界) */
    CHECK(can_baud_hz(36000000u, 1023, 15, 7) == 1406u);
    CHECK(can_baud_hz(36000000u, 0, 0, 0) == 12000000u);
    CHECK(can_baud_hz(36000000u, 5, 11, 4) == 333333u);  /* 36M/(6*18) */
    /* 二期勘误: 一期断言 (0,7,8) 的 ts2=8 超出 BTR bits 20:22 (3 位
     * 域), 物理不可表示, 防御正确拒绝 — 改为等价合法组合 ts1=8/ts2=7
     * (仍 18 TQ → 36M/(1*18) = 2M) */
    CHECK(can_baud_hz(36000000u, 0, 8, 7)  == 2000000u);
    /* 组3 非法输入防御 (二期新增): 零时钟/位域越宽 → 0 哨兵 */
    CHECK(can_baud_hz(0u, 3, 12, 5) == 0u);
    CHECK(can_baud_hz(36000000u, 1024, 12, 5) == 0u);
    CHECK(can_baud_hz(36000000u, 3, 16, 5) == 0u);
    CHECK(can_baud_hz(36000000u, 3, 12, 8) == 0u);
    /* 组4 序列-拒绝路径: 硬件不应答 (mock MSR 恒 0) → INAK 超时
     * 返回 -1, 且不带病继续配置 (BTR 未写) */
    CHECK(can_init_500k() == -1);
    CHECK(f103_mock_CAN.MCR == (1u << 0));    /* 只写了 INRQ */
    CHECK(f103_mock_CAN.BTR == 0u);
    /* 组5 序列-完成路径: 模拟硬件置 INAK → 全序列走通; mock MSR 为
     * 静态内存无法模拟"退出初始化后 INAK 自清", rc==-2 是 mock 局限,
     * 断言重点=寄存器终态; 退出等待的通过侧语义单测
     * F-213: MCR 期望值随初始化序列修复而变——原实现整字赋值把 INRQ
     * 清零, 终态只剩 bit4; 现改读改写, RFLM(bit3) 应保留。 */
    f103_mock_CAN.MSR = (1u << 0);            /* 模拟硬件 INAK(bit0) 应答 */
    CHECK(can_init_500k() == -2);
    CHECK(f103_mock_CAN.MCR == ((1u << 3) | (1u << 4)));  /* RFLM+NART, INRQ 已清 */
    CHECK(f103_mock_CAN.BTR == ((3u << 0) | (10u << 16) | (5u << 20)));
    f103_mock_CAN.MSR = 0;
    CHECK(can_wait_msr_bit(1u << 0, 0) == 0); /* INAK(bit0) 已清 → 等待通过 */
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
