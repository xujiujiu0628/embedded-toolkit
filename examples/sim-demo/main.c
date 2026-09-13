/* F-150 sim-demo — qemu-system-arm stm32vldiscovery 上跑的最小示例固件。
 *
 * 打印符合自带 .workbench/expectations.json 契约的输出后, 以
 * SYS_EXIT_EXTENDED (0x20) 干净退出 (F-149: M-profile 旧 SYS_EXIT 0x18
 * 被 qemu 无声忽略)。semihosting SYS_WRITE0 输出走 qemu stderr。
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
void Default_Handler(void);

__attribute__((section(".isr_vector")))
const void *vector[] = {
    (void *)0x20002000,   /* STM32F100: 8K RAM @ 0x20000000 */
    Reset_Handler,        /* Reset */
    Default_Handler,      /* NMI */
    Default_Handler,      /* HardFault — 向量表必须完整, 否则 fault 取到
                             数据当向量跳进字符串字节 (F-149 施工实录) */
};

void Default_Handler(void)
{
    print("=== HARDFAULT ===\n");
    for (;;) {
    }
}

void Reset_Handler(void)
{
    print("=== sim-demo boot ===\n");
    print("[init] CLK OK\n");
    for (int i = 1; i <= 2; i++) {
        print("TGL 1\n");   /* TGL <i> 语义见契约 FR-TGL-01 (patterns 匹配) */
        for (volatile int d = 0; d < 10000; d++) {
        }
    }
    print("ADC raw=3961 mv=3192\n");
    print("=== done ===\n");
    {
        volatile u32 exit_block[2] = {0x20026, 0};
        semihost(0x20 /* SYS_EXIT_EXTENDED */, (void *)exit_block);
    }
    for (;;) {
    }
}
