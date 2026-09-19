# f103-exti

EXTI 线 0 (PA0) 上升沿中断最小样例（GPIO→AFIO 映射→IMR/RTSR→NVIC）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.EXTI / AFIO (寄存器/位名见 main.c 各行 anchor; EXTI0 IRQ=6 记 GAP-D-3)