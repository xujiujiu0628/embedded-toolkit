/* F-149 spike 附加: USART1 直写通路 — qemu stm32vldiscovery 的 USART 模型
 * 是否把 DR 写转发到 -serial stdio (qemu 通常不 gate 时钟, CR1 UE|TE 即发)。 */
typedef unsigned long u32;
typedef unsigned char u8;

#define USART1_BASE 0x40013800u
static volatile u32 *const USART1 = (volatile u32 *)USART1_BASE;

static void usart_print(const char *s)
{
    USART1[3] = (1u << 13) | (1u << 3);   /* CR1: UE | TE */
    for (const char *p = s; *p; p++) {
        USART1[1] = (u8)*p;               /* DR */
        while (!(USART1[0] & (1u << 6))) { /* 等 TC */
        }
    }
}

void Reset_Handler(void);

__attribute__((section(".isr_vector")))
const void *vector[] = {
    (void *)0x20002000,
    Reset_Handler,
};

void Reset_Handler(void)
{
    usart_print("=== usart1 boot ===\n");
    usart_print("ADC raw=3961 mv=3192\n");
    for (;;) {
    }
}
