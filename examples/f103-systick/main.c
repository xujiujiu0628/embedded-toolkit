/* f103-systick — T1 样例 (编译级)。
 * 用途: SysTick 1kHz 节拍 + delay_ms 最小样例 (100ms 心跳)。
 * 生成方式: gen_periph --type systick --freq 1000
 * ref.json anchor: peripherals.SysTick (Cortex-M3 核心; CTRL 位与生成器契约同源)
 * 组装变换: 仅两处 — ①生成体裸语句包入 systick_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 基于 SysTick 的延时计数 */
static volatile uint32_t tick_ms;

/* SysTick ISR */
void SysTick_Handler(void) {
    tick_ms++;                  // F-087: 必须递增, 否则 delay_ms 永久挂死
    // called every 1000us — 用户代码加在这里
}

void delay_ms(uint32_t ms) {
    uint32_t start = tick_ms;
    while ((tick_ms - start) < ms) { __WFI(); }
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void systick_init(void) {
/* SysTick — 1000Hz (1000us interval), 72MHz core clock */
SysTick->LOAD = 71999;         // 72MHz/1000 - 1
SysTick->VAL  = 0;
SysTick->CTRL = SysTick_CTRL_ENABLE | SysTick_CTRL_TICKINT | SysTick_CTRL_CLKSOURCE;

}


int main(void)
{
    systick_init();
    for (;;) {
        /* 最小使用场景: 100ms 周期节拍 */
        delay_ms(100);
    }
}
