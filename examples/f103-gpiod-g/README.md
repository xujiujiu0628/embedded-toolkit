# f103-gpiod-g

GPIOD/E/F/G 四端口推挽输出合并样例（C8T6 无 D~G 端口，参考型样例）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.GPIOD~GPIOG (注: available_on_c8 均=false; RCC.APB2ENR bits 5..8)