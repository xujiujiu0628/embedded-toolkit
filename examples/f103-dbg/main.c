/* f103-dbg — T3 手写寄存器级样例（编译级 + host mock）。
 * 用途: DBGMCU 基址/IDCODE 位域切分/DBGCR 调试保持位编码最小实做。
 * 补做理由: WB-20260919-04 一期以"ref.json 无 DBGMCU 条目、零数据可锚定"
 *          为由未做 dbg——该理由失实（WB-20260920-02 勘误④：ref.json 存在
 *          DBG 条目 base 0xE0042000、IDCODE/CR 位名齐全）。本样例即该锚定项。
 *
 * ref.json anchor: peripherals.DBG（base 0xE0042000；IDCODE@0x00 DEV_ID 0:11 /
 *                  REV_ID 16:31；CR@0x04 位名 DBG_SLEEP/DBG_STOP/DBG_STANDBY/
 *                  TRACE_IOEN/TRACE_MODE 6:7/DBG_IWDG_STOP/DBG_WWDG_STOP/
 *                  DBG_TIM1_STOP … DBG_CAN2_STOP）。
 * arch-facts anchor: data/stm32f103-arch-facts.json → dbg.cr_bits
 *                  （位号逐条锚 CMSIS:stm32f103xg.h:11100-11142 的
 *                   DBGMCU_CR_*_Pos；一致性由 tests/test_ref_arch_facts.py 钉）。
 *
 * 口径注记（只注不改，见 WB-20260920-05 报告 §新发现 GAP）:
 *   - ref.json peripherals.DBG.bus == "?"（DBG 无 RCC 使能位可依，故未登记总线）；
 *   - DBG 无中断向量；
 *   - ref.json DBG.CR 列有 DBG_CAN2_STOP(bit21)，但 stm32f103xg.h 无对应锚点
 *     （F103 无 CAN2 实例）—— 本样例的有效位掩码仍按 ref.json 位表取，未私改。
 *
 * 硬件验收: 未做（编译级样例）
 * mock (WB-20260920-05): host 断言 ≥5 组——基址/偏移锚定、IDCODE 位域切分
 *          已知答案、DBGCR 组合位型手算 0x107、非法位防御、清零回读。
 */
#include "f103_regs.h"

/* ── DBGMCU 本地寄存器层（共享头 f103_regs.h 未收 DBG，本样例自带）──
 * 偏移逐项 = ref.json peripherals.DBG.registers.*.offset */
typedef struct {
    volatile uint32_t IDCODE;   /* ref.json DBG.IDCODE offset 0x0 */
    volatile uint32_t CR;       /* ref.json DBG.CR     offset 0x4 */
} DBG_TypeDef;

#define DBG_BASE          0xE0042000UL   /* ref.json peripherals.DBG.base */
#define DBG               ((DBG_TypeDef *)DBG_BASE)

/* ── DBGCR 位（位号 = ref.json DBG.CR bits，与 arch-facts dbg.cr_bits 同源）── */
#define DBG_CR_DBG_SLEEP        (1UL << 0)
#define DBG_CR_DBG_STOP         (1UL << 1)
#define DBG_CR_DBG_STANDBY      (1UL << 2)
#define DBG_CR_TRACE_IOEN       (1UL << 5)
#define DBG_CR_TRACE_MODE_MASK  (3UL << 6)
#define DBG_CR_DBG_IWDG_STOP    (1UL << 8)
#define DBG_CR_DBG_WWDG_STOP    (1UL << 9)
#define DBG_CR_DBG_TIM1_STOP    (1UL << 10)

/* ref.json DBG.CR 已登记位号全集的手算掩码:
 *   0,1,2 | 5..21  → 0x7 | 0x3FFFE0 = 0x3FFFE7
 * （逐位表达式与手算常数由 host 组3 互证，防手写走样）*/
#define DBG_CR_VALID_MASK \
    ((1UL << 0) | (1UL << 1) | (1UL << 2) | (1UL << 5) | (1UL << 6) | \
     (1UL << 7) | (1UL << 8) | (1UL << 9) | (1UL << 10) | (1UL << 11) | \
     (1UL << 12) | (1UL << 13) | (1UL << 14) | (1UL << 15) | (1UL << 16) | \
     (1UL << 17) | (1UL << 18) | (1UL << 19) | (1UL << 20) | (1UL << 21))
#define DBG_CR_VALID_MASK_HANDCALC 0x3FFFE7UL

/* 低功耗调试保持组合（手算: bit0|bit1|bit2|bit8 = 0x107）*/
#define DBG_HOLD_LOWPOWER \
    (DBG_CR_DBG_SLEEP | DBG_CR_DBG_STOP | DBG_CR_DBG_STANDBY | \
     DBG_CR_DBG_IWDG_STOP)

#ifdef F103_MOCK_REGS
#if defined(F103_MOCK_DBG)
static DBG_TypeDef f103_mock_DBG __attribute__((unused));
#undef DBG
#define DBG (&f103_mock_DBG)
#endif
#endif

/* ── 配置/读取序列（target 写真寄存器 / host 写重定向结构，两态共用）── */
static uint32_t dbg_read_idcode(void)
{
    return DBG->IDCODE;                  /* ref.json DBG.IDCODE bits 0:31 */
}

static uint32_t dbg_dev_id(uint32_t idcode)
{
    return idcode & 0x0FFFu;             /* DEV_ID = bits 0:11 */
}

static uint32_t dbg_rev_id(uint32_t idcode)
{
    return (idcode >> 16) & 0xFFFFu;     /* REV_ID = bits 16:31 */
}

/* 非法位防御: 未登记位不静默写入（返回 -1 且不触碰寄存器）*/
static int dbg_cr_write(uint32_t value)
{
    if ((value & ~DBG_CR_VALID_MASK) != 0UL) {
        return -1;
    }
    DBG->CR = value;                     /* ref.json DBG.CR bits 0:31 */
    return 0;
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    uint32_t idcode = dbg_read_idcode();
    (void)dbg_dev_id(idcode);
    (void)dbg_rev_id(idcode);
    (void)dbg_cr_write(DBG_HOLD_LOWPOWER);
    for (;;) {
        __WFI();
    }
}
#else
#include <stddef.h>
#include <stdio.h>

static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

int main(void)
{
    /* 组1 基址/偏移锚定（ref.json peripherals.DBG: base 0xE0042000,
     * IDCODE@0x0, CR@0x4）*/
    CHECK(DBG_BASE == 0xE0042000UL);
    CHECK(offsetof(DBG_TypeDef, IDCODE) == 0u);
    CHECK(offsetof(DBG_TypeDef, CR) == 4u);

    /* 组2 IDCODE 位域切分已知答案（手算）:
     * 0x20036410 → DEV_ID = 0x410, REV_ID = 0x2003 */
    f103_mock_DBG.IDCODE = 0x20036410u;
    CHECK(dbg_read_idcode() == 0x20036410u);
    CHECK(dbg_dev_id(0x20036410u) == 0x410u);
    CHECK(dbg_rev_id(0x20036410u) == 0x2003u);
    /* 位域边界: DEV_ID 不吃 bit12；REV_ID 只吃 16:31 */
    CHECK(dbg_dev_id(0x0000FFFFu) == 0xFFFu);
    CHECK(dbg_rev_id(0xFFFF0000u) == 0xFFFFu);
    CHECK(dbg_rev_id(0x0000FFFFu) == 0x0000u);

    /* 组3 DBGCR 组合位型手算 + 掩码自洽:
     * HOLD = SLEEP(0)|STOP(1)|STANDBY(2)|IWDG_STOP(8) = 0x107；
     * 掩码逐位表达式 == 手算常数 0x3FFFE7 */
    CHECK(DBG_CR_VALID_MASK == DBG_CR_VALID_MASK_HANDCALC);
    CHECK(DBG_HOLD_LOWPOWER == 0x107u);
    f103_mock_DBG.CR = 0u;
    CHECK(dbg_cr_write(DBG_HOLD_LOWPOWER) == 0);
    CHECK(f103_mock_DBG.CR == 0x107u);
    /* 叠加 TRACE_IOEN(5) + TIM1_STOP(10) 再手算: 0x107|0x20|0x400 = 0x527 */
    CHECK(dbg_cr_write(DBG_HOLD_LOWPOWER | DBG_CR_TRACE_IOEN |
                       DBG_CR_DBG_TIM1_STOP) == 0);
    CHECK(f103_mock_DBG.CR == 0x527u);

    /* 组4 非法位防御（未登记位拒绝且不留痕）:
     * bit4（ref.json DBG.CR 未登记）、bit22（超 21 位表）、bit31 全拒 */
    CHECK(dbg_cr_write(1UL << 4) == -1);
    CHECK(f103_mock_DBG.CR == 0x527u);
    CHECK(dbg_cr_write(1UL << 22) == -1);
    CHECK(dbg_cr_write(1UL << 31) == -1);
    CHECK(f103_mock_DBG.CR == 0x527u);

    /* 组5 清零回读 + 满档合法位型（TRACE_MODE 6:7 = 11b 含在内）*/
    CHECK(dbg_cr_write(DBG_CR_TRACE_MODE_MASK) == 0);
    CHECK(f103_mock_DBG.CR == 0xC0u);
    CHECK(dbg_cr_write(0UL) == 0);
    CHECK(f103_mock_DBG.CR == 0u);

    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
