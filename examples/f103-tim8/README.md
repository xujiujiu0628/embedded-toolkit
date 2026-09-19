# f103-tim8

TIM8 高级定时器最小样例（与 TIM1 同模板，实例差异见 README）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.TIM8 (注: available_on_c8=false — C8T6 无 TIM8, 参考型样例; 引脚未登记 GAP-D-4)