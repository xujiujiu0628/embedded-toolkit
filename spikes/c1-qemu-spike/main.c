/* F-149 spike: 最小 Cortex-M3 固件 — semihosting SYS_WRITE0 打印,
 * 两种收尾形态:
 *   main.c 默认 (EXIT_AFTER_PRINT=1): 打印完走 SYS_EXIT → qemu 正常退出;
 *   -DEXIT_AFTER_PRINT=0: 打印完死循环 → 测外部 timeout 行为。
 * 目标机: qemu-system-arm -M stm32vldiscovery (STM32F100, Cortex-M3, 8K RAM)。
 */
typedef unsigned long u32;

static inline void semihost(u32 op, void *arg)
{
    register void *r1 __asm("r1") = arg;
    register u32 r0 __asm("r0") = op;
    __asm volatile("bkpt 0xAB" : : "r"(r0), "r"(r1) : "memory");
}

static void print(const char *s)
{
    semihost(0x04 /* SYS_WRITE0 */, (void *)s);
}

void Reset_Handler(void);

__attribute__((section(".isr_vector")))
const void *vector[] = {
    (void *)0x20002000,   /* initial SP: 8K RAM @ 0x20000000 */
    Reset_Handler,
};

void Reset_Handler(void)
{
    print("=== boot ===\n");
    print("[init] CLK OK\n");
    for (int i = 0; i < 3; i++) {
        print("TGL 1\n");
        for (volatile int d = 0; d < 20000; d++) {
        }
    }
    print("ADC raw=3961 mv=3192\n");
    print("=== done ===\n");
#if USE_EXIT_EXTENDED
    /* M-profile 正确退出姿势: SYS_EXIT_EXTENDED (0x20), r1 指向 64 位
     * {reason, subcode} 内存块 (旧 0x18 SYS_EXIT 在 qemu M-profile 被
     * 无声忽略 — qemu 进程不退出, F-149 实测结论) */
    volatile u32 exit_block[2] = {0x20026, 0};
    semihost(0x20, (void *)exit_block);
#elif EXIT_AFTER_PRINT
    semihost(0x18 /* SYS_EXIT */, (void *)0x20026 /* ADP_Stopped_ApplicationExit */);
#endif
    for (;;) {
    }
}
