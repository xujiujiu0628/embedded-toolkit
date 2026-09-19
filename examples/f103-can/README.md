# f103-can

bxCAN 初始化时序最小样例（INRQ 进初始化→BTR 位时序→出初始化）+ 波特率换算可测。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.CAN (引脚映射 ref.json 未登记 — GAP-D-4, 本样例只配核心寄存器)