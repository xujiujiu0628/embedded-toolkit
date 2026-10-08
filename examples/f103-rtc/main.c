/* f103-rtc — T2 手写寄存器级样例 (编译级)。
 * 用途: 备份域解锁 → LSE 起振 → 选 LSE 为 RTC 时钟 → 配置 1Hz → 轮询秒标志。
 * ref.json anchor: peripherals.RTC (CRH/CRL/PRLH/PRLL 位名), RCC.BDCR
 *                  (LSEON/LSERDY/RTCSEL/RTCEN), PWR.CR bit8=DBP,
 *                  RCC.APB1ENR bits 27/28=BKPEN/PWREN。
 * 硬件验收: ✅ 2026-10-08 真机 PASS (F103C8T6+ST-Link, F-223 修复后复验;
 *          buggy 先红=BDCR 0x8203/LSI 且 RTC 停摆); 详见 README
 * mock 二期 (WB-20260920-02): 新增 host mock — 备份域链/BDCR 位型/
 *          预分频已知答案 + 日历进位换算。
 */
#include "f103_regs.h"

static void rtc_init_1hz(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_PWREN | RCC_APB1ENR_BKPEN;
    __DSB();
    PWR->CR |= PWR_CR_DBP;               /* 备份域写使能 */
    RCC->BDCR |= RCC_BDCR_LSEON;         /* ref.json RCC.BDCR bit0 */
    while (!(RCC->BDCR & RCC_BDCR_LSERDY)) {   /* bit1=LSERDY */
    }
    RCC->BDCR = (RCC->BDCR & ~(3UL << 8))  /* RTCSEL bits 8:9 */
              | RCC_BDCR_RTCSEL_LSE
              | RCC_BDCR_RTCEN;            /* bit15 */
    RTC->CRL |= (1UL << 3);               /* RSF=1 等待同步 (CRL bit3) */
    RTC->CRL |= (1UL << 4);               /* CNF=1 进入配置模式 (bit4) */
    RTC->PRLH = 0;                        /* ref.json RTC.PRLH bits 0:3 */
    RTC->PRLL = 32767;                    /* LSE 32768Hz → 1Hz (bits 0:15) */
    RTC->CRH |= (1UL << 0);               /* SECIE 秒中断使能 (CRH bit0) */
    RTC->CRL &= ~(1UL << 4);              /* CNF=0 退出配置模式 */
    /* F-213: RTOFF (CRL bit5, 只读) = 1 表示"上次写已完成/寄存器已解锁",
     * 故应等它"变 1"。原写 `while (CRL & (1<<5))` 等的是它变 0, 极性反了:
     * 写入后硬件立即置 1, 循环一次都不进 (等于没等); 若恰在写周期内采样到 0
     * 则死等。正确判据 = while (!(CRL & (1<<5)))。 */
#ifndef F103_SAMPLE_HOST_TEST
    while (!(RTC->CRL & (1UL << 5))) {    /* 真机: 等 RTOFF (bit5) 置 1 = 写完成 */
    }
#else
    /* host: mock 是静态内存, 无任何代码会置 RTOFF (F-215 复核: 全文件只有
     * 此处读取该位), 故真机版的无界忙等在这里必然死等 → 用有界轮询兜底,
     * 跑满 guard 次后落出, 与本仓其它样例 (如 f103-can 的 can_wait_msr_bit)
     * 同口径。
     *
     * F-215 订正措辞: 此前注释称此循环"模拟硬件应答""超时返回"——两者都不
     * 成立。它**只是不死等**: 没有应答方, guard 耗尽即落出, 既不返回状态码
     * 也不置位。断言重点在 rtc_init_1hz 之后的寄存器终态 (mock 段组2/组4),
     * 等待行为本身在 host 下不可测——真机极性的验证依据是 RM0008 的 RTOFF
     * 语义与真板运行, 不是这个循环。
     *
     * 也不是"绕过忙等": F-213 原写 `while (CRL & (1<<5))`, 极性反了, 在恒 0
     * 的 mock 上一次都不进循环——等于把等待整个跳过, 同样验证不了什么。 */
    {
        uint32_t guard = 1000000u;
        while (guard--) {
            if (RTC->CRL & (1UL << 5)) {   /* 无人置位 → 恒不成立, 仅保不死等 */
                break;
            }
        }
    }
#endif
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    rtc_init_1hz();
    for (;;) {
        /* 最小使用场景: 轮询秒标志并写 1 清除 (CRL bit0=SECF) */
        if (RTC->CRL & (1UL << 0)) {
            RTC->CRL &= ~(1UL << 0);
        }
        __WFI();
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

/* 日历换算 (host-only 推导辅助): RTC CNT = 秒计数 (32 位, ref
 * CNTH/CNTL 各 0:15) → 时:分:秒+日进位; 期望常数均为手算 */
static uint32_t rtc_hms_sec(uint32_t cnt)  { return cnt % 60u; }
static uint32_t rtc_hms_min(uint32_t cnt)  { return (cnt / 60u) % 60u; }
static uint32_t rtc_hms_hour(uint32_t cnt) { return (cnt / 3600u) % 24u; }
static uint32_t rtc_hms_day(uint32_t cnt)  { return cnt / 86400u; }

int main(void)
{
    /* 模拟硬件应答: LSE 已起振 (LSERDY=1) — 否则 init 的忙等在 mock
     * 下永不退出。RTOFF 不预置: F-213 已把忙等极性改正为"等 RTOFF=1",
     * 且 host 分支改用有界轮询 (见 rtc_init_1hz), 预置与否都不死等,
     * 断言重点是寄存器终态而非等待时长。 */
    f103_mock_RCC.BDCR = RCC_BDCR_LSEON | RCC_BDCR_LSERDY;
    /* 组1 备份域解锁链: APB1 PWREN|BKPEN + PWR.DBP (bit8) */
    rtc_init_1hz();
    CHECK(f103_mock_RCC.APB1ENR & RCC_APB1ENR_PWREN);
    CHECK(f103_mock_RCC.APB1ENR & RCC_APB1ENR_BKPEN);
    CHECK(f103_mock_PWR.CR & PWR_CR_DBP);
    /* 组2 BDCR 终态位型 (手算): LSEON(0)|LSERDY(1)|RTCSEL=01b(8:9)
     * |RTCEN(15) = 0x3|0x100|0x8000 = 0x8103
     * F-223 订正: 原期望 0x8203 (=10b=LSI 编码) 与错误宏值互相自证;
     * 真机实测 BDCR=0x8203 且 RTC 停摆 (CNT/DIV 冻结), 双源 (RM0008 +
     * CMSIS RCC_BDCR_RTCSEL_LSE=0x100) 核实后订正为 01b 编码。 */
    CHECK(f103_mock_RCC.BDCR == 0x8103u);
    /* 组3 1Hz 预分频已知答案: 32768Hz/(32767+1) = 1Hz;
     * PRLH=0 (bits 0:3) / PRLL=32767 (bits 0:15); SECIE=CRH bit0 */
    CHECK(f103_mock_RTC.PRLH == 0u && f103_mock_RTC.PRLL == 32767u);
    CHECK(f103_mock_RTC.CRH & 1u);
    /* 组4 CNF 配置模式进出位型 (手算): CRL = RSF(3) = 0x08,
     * CNF(4) 已退出, RTOFF(5) 未预置 */
    CHECK(f103_mock_RTC.CRL == 0x08u);
    /* 组5 日历进位换算 (手算): 3661s=1:01:01; 86399s=23:59:59 日 0;
     * 86400s → 0:0:0 且日进位 1 */
    CHECK(rtc_hms_hour(3661u) == 1u && rtc_hms_min(3661u) == 1u
          && rtc_hms_sec(3661u) == 1u);
    CHECK(rtc_hms_hour(86399u) == 23u && rtc_hms_min(86399u) == 59u
          && rtc_hms_sec(86399u) == 59u && rtc_hms_day(86399u) == 0u);
    CHECK(rtc_hms_hour(86400u) == 0u && rtc_hms_min(86400u) == 0u
          && rtc_hms_sec(86400u) == 0u && rtc_hms_day(86400u) == 1u);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
