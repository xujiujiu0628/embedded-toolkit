# f103-fsmc

FSMC 存储块 1 (SRAM/NOR) 使能与读时序配置参考型样例（C8T6 无 FSMC）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.FSMC (注: available_on_c8=false; BCR1/BTR1 位域 ref.json, 位名 GAP-D-4)