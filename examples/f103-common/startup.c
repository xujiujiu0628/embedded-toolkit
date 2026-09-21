/*
 * startup.c — 样例工厂共享最小启动桩 (WB-20260919-04)
 *
 * 向量表槽位纪律: 设备中断槽位逐项注明来源 —
 *   [ref]  = data/stm32f103-ref.json _relationships.<P>.irq.number
 *   [ref]  (F-179 转正) = 原 [GAP-D-3] 的 9 个槽位已于 F-179 正式登记入
 *               _relationships (TIM9/12/13/14、EXTI0、RTC、TIM5/6/7),
 *               槽位值与 IRQ 号逐一对应, 锚 stm32f103xg.h (见各条注记)。
 *               本次仅注记措辞随动, 向量表内容零字节变。
 * 槽位 0 值 = 初始栈顶 (link.ld: RAM 20K @ 0x20000000 → 0x20005000)。
 * 未登记槽位填 0 (不可达; 对应外设未使能中断)。
 */
#include <stdint.h>

int main(void);
void Reset_Handler(void);
void Default_Handler(void);

/* 样例会用到的设备中断 — 全部 weak alias 到 Default_Handler,
 * 样例在 main.c 定义同名强符号即接管。 */
void NMI_Handler(void)       __attribute__((weak, alias("Default_Handler")));
void HardFault_Handler(void) __attribute__((weak, alias("Default_Handler")));
void MemManage_Handler(void) __attribute__((weak, alias("Default_Handler")));
void BusFault_Handler(void)  __attribute__((weak, alias("Default_Handler")));
void UsageFault_Handler(void)__attribute__((weak, alias("Default_Handler")));
void SVC_Handler(void)       __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void)  __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void)    __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void)   __attribute__((weak, alias("Default_Handler")));

void RTC_IRQHandler(void)            __attribute__((weak, alias("Default_Handler")));  /* [ref] RTC irq=3 (锚 stm32f103xg.h:85) */
void EXTI0_IRQHandler(void)          __attribute__((weak, alias("Default_Handler")));  /* [ref] EXTI0 irq=6 (锚 stm32f103xg.h:88) */
void ADC1_2_IRQHandler(void)         __attribute__((weak, alias("Default_Handler")));  /* [ref] ADC1 irq=18 */
void TIM1_BRK_TIM9_IRQHandler(void)  __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM9 irq=24 (锚 stm32f103xg.h:106) */
void TIM1_UP_TIM10_IRQHandler(void)  __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM1 irq=25 */
void TIM2_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM2 irq=28 */
void TIM3_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM3 irq=29 */
void TIM4_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM4 irq=30 */
void I2C1_EV_IRQHandler(void)        __attribute__((weak, alias("Default_Handler")));  /* [ref] I2C1 irq=31 */
void I2C2_EV_IRQHandler(void)        __attribute__((weak, alias("Default_Handler")));  /* [ref] I2C2 irq=33 */
void SPI1_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [ref] SPI1 irq=35 */
void SPI2_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [ref] SPI2 irq=36 */
void USART1_IRQHandler(void)         __attribute__((weak, alias("Default_Handler")));  /* [ref] USART1 irq=37 */
void USART2_IRQHandler(void)         __attribute__((weak, alias("Default_Handler")));  /* [ref] USART2 irq=38 */
void USART3_IRQHandler(void)         __attribute__((weak, alias("Default_Handler")));  /* [ref] USART3 irq=39 */
void TIM8_BRK_TIM12_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM12 irq=43 (锚 stm32f103xg.h:125) */
void TIM8_UP_TIM13_IRQHandler(void)  __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM13 irq=44 (锚 stm32f103xg.h:126) */
void TIM8_TRG_COM_TIM14_IRQHandler(void) __attribute__((weak, alias("Default_Handler"))); /* [ref] TIM14 irq=45 (锚 stm32f103xg.h:127) */
void TIM5_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM5 irq=50 (锚 stm32f103xg.h:132) */
void TIM6_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM6 irq=54 (锚 stm32f103xg.h:136) */
void TIM7_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [ref] TIM7 irq=55 (锚 stm32f103xg.h:137) */

typedef void (*isr_handler_t)(void);

__attribute__((section(".isr_vector"), used))
const isr_handler_t vector_table[] = {
    [0]  = (isr_handler_t)0x20005000UL,  /* 初始栈顶 — RAM 20K 顶 (link.ld) */
    [1]  = Reset_Handler,
    [2]  = NMI_Handler,
    [3]  = HardFault_Handler,
    [4]  = MemManage_Handler,
    [5]  = BusFault_Handler,
    [6]  = UsageFault_Handler,
    [11] = SVC_Handler,
    [12] = DebugMon_Handler,
    [14] = PendSV_Handler,
    [15] = SysTick_Handler,
    /* 设备中断 (16+n): 槽位来源见上方 alias 声明的逐项注记 */
    [16 + 3]  = RTC_IRQHandler,
    [16 + 6]  = EXTI0_IRQHandler,
    [16 + 18] = ADC1_2_IRQHandler,
    [16 + 24] = TIM1_BRK_TIM9_IRQHandler,
    [16 + 25] = TIM1_UP_TIM10_IRQHandler,
    [16 + 28] = TIM2_IRQHandler,
    [16 + 29] = TIM3_IRQHandler,
    [16 + 30] = TIM4_IRQHandler,
    [16 + 31] = I2C1_EV_IRQHandler,
    [16 + 33] = I2C2_EV_IRQHandler,
    [16 + 35] = SPI1_IRQHandler,
    [16 + 36] = SPI2_IRQHandler,
    [16 + 37] = USART1_IRQHandler,
    [16 + 38] = USART2_IRQHandler,
    [16 + 39] = USART3_IRQHandler,
    [16 + 43] = TIM8_BRK_TIM12_IRQHandler,
    [16 + 44] = TIM8_UP_TIM13_IRQHandler,
    [16 + 45] = TIM8_TRG_COM_TIM14_IRQHandler,
    [16 + 50] = TIM5_IRQHandler,
    [16 + 54] = TIM6_IRQHandler,
    [16 + 55] = TIM7_IRQHandler,
    /* 其余槽位 = 0: 对应外设中断未使能, 不可达 */
};

void Reset_Handler(void)
{
    extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss;
    uint32_t *src = &_sidata;
    uint32_t *dst = &_sdata;

    while (dst < &_edata) {          /* .data: flash → RAM 拷贝 */
        *dst++ = *src++;
    }
    dst = &_sbss;
    while (dst < &_ebss) {           /* .bss 清零 */
        *dst++ = 0;
    }
    (void)main();
    for (;;) {                       /* main 返回即停 (不应到达) */
    }
}

void Default_Handler(void)
{
    for (;;) {
    }
}
