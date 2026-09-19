# f103-nvic

NVIC 中断控制最小样例（使能/禁用/优先级，以 TIM2 IRQ 为例）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.NVIC (ref.json 仅登记 ISER — ICER/IP 为 Cortex-M3 架构常量, GAP-D-1)