/* f103-flash — T2 手写寄存器级样例 (编译级)。
 * 用途: 仅演示 KEYR 解锁序列 → 读回 CR.LOCK 确认 → 立即重新上锁;
 *       外加 72MHz 下的预取/等待周期配置。
 * ⚠ 红字声明: 本样例不实际执行任何写入/擦除 (不写 PG/PER/MER/STRT)。
 * ref.json anchor: peripherals.FLASH (ACR/KEYR/SR/CR 偏移与位名:
 *                  CR bit7=LOCK, ACR bits 0:2=LATENCY 4=PRFTBE)。
 * GAP-D-4: KEYR 魔数 0x45670123/0xCDEF89AB 为 ST 架构常量, ref.json 未登记。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void flash_latency_prefetch_init(void)
{
    /* 72MHz → 2 等待周期 + 预取使能
     * (数据源: data/f103_known_issues.json "Flash.wait_states") */
    FLASH->ACR = (2UL << 0) | (1UL << 4);
}

static int flash_unlock_probe(void)
{
    FLASH->KEYR = 0x45670123u;            /* 钥匙 1 (GAP-D-4) */
    FLASH->KEYR = 0xCDEF89ABu;            /* 钥匙 2 */
    if (FLASH->CR & (1UL << 7)) {         /* ref.json FLASH.CR bit7=LOCK */
        return -1;                        /* LOCK 仍置位 = 解锁失败 */
    }
    FLASH->CR |= (1UL << 7);              /* 立即重新上锁 */
    return 0;
}

int main(void)
{
    flash_latency_prefetch_init();
    for (;;) {
        /* 最小使用场景: 解锁→确认→上锁 (无任何写入/擦除动作) */
        if (flash_unlock_probe() != 0) {
            for (;;) {
            }
        }
        for (volatile int d = 0; d < 100000; d++) {
        }
    }
}
