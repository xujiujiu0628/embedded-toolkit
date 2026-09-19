# f103-tim6-7

TIM6/TIM7 基本定时器合并样例（双实例不同周期，轮询 UIF）+ 换算纯函数可测。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 可测性: MOCK 哨兵 — `make test` 用 host gcc 跑寄存器序列/纯逻辑断言
- 寄存器数据来源: ref.json peripherals.TIM6 / TIM7 (注: available_on_c8=false — C8T6 无基本定时器, 参考型样例)