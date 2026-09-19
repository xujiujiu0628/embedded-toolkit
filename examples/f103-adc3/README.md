# f103-adc3

ADC3 单次转换核心配置参考型样例（C8T6 无 ADC3 — 高密度才有；引脚未登记 GAP-D-4）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.ADC3 (注: available_on_c8=false; 布局同 ADC1, 引脚未登记 GAP-D-4)