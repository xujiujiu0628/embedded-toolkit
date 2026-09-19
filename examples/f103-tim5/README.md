# f103-tim5

TIM5 通用定时器 PWM 最小样例（C8T6 无 TIM5, 参考型）+ 分频换算纯函数可测。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 可测性: MOCK 哨兵 — `make test` 用 host gcc 跑寄存器序列/纯逻辑断言
- 寄存器数据来源: ref.json peripherals.TIM5 (注: available_on_c8=false; 引脚未登记 GAP-D-4, 本样例只配核心寄存器)