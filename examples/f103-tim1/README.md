# f103-tim1

TIM1 高级定时器互补输出 + 刹车（break）最小样例（MOE 主输出使能）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.TIM1 (CH1 引脚 PA8 来自 ref.json _relationships; CH1N/BKIN 引脚未登记 GAP-D-4)