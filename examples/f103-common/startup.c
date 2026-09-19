/*
 * startup.c — 样例工厂共享最小启动桩 (WB-20260919-04)
 *
 * 向量表槽位纪律: 设备中断槽位逐项注明来源 —
 *   [ref]  = data/stm32f103-ref.json _relationships.<P>.irq.number
 *   [GAP-D-3] = ref.json 未登记该外设 IRQ 号, 槽位值沿用 ref.json 自身的
 *               共享命名先例 (TIM1_UP_TIM10_IRQn=25 ⇒ TIM1_BRK_TIM9=24,
 *               TIM8_BRK_TIM12=43, TIM8_UP_TIM13=44, TIM8_TRG_COM_TIM14=45)
 *               与 ST F1 中断映射的对应槽位, 详见 GAPREPORT; 不得默写新数。
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

void RTC_IRQHandler(void)            __attribute__((weak, alias("Default_Handler")));  /* [GAP-D-3] 槽位 3 */
void EXTI0_IRQHandler(void)          __attribute__((weak, alias("Default_Handler")));  /* [GAP-D-3] 槽位 6 */
void ADC1_2_IRQHandler(void)         __attribute__((weak, alias("Default_Handler")));  /* [ref] ADC1 irq=18 */
void TIM1_BRK_TIM9_IRQHandler(void)  __attribute__((weak, alias("Default_Handler")));  /* [GAP-D-3] 槽位 24 */
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
void TIM8_BRK_TIM12_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));  /* [GAP-D-3] 槽位 43 */
void TIM8_UP_TIM13_IRQHandler(void)  __attribute__((weak, alias("Default_Handler")));  /* [GAP-D-3] 槽位 44 */
void TIM8_TRG_COM_TIM14_IRQHandler(void) __attribute__((weak, alias("Default_Handler"))); /* [GAP-D-3] 槽位 45 */
void TIM5_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [GAP-D-3] 槽位 50 */
void TIM6_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [GAP-D-3] 槽位 54 */
void TIM7_IRQHandler(void)           __attribute__((weak, alias("Default_Handler")));  /* [GAP-D-3] 槽位 55 */

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
