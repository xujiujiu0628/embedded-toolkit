# f103-tim9-14

TIM9~TIM14 通用定时器合并样例（TIM9 双通道 + TIM10 单通道实做，实例差异表见 README）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.TIM9~TIM14 (ref.json 外设 bus 字段与 RCC 使能位矛盾 — GAP-D-5, 依 RCC 位数据)