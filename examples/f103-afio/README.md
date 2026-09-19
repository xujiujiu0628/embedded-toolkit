# f103-afio

AFIO 复用重映射最小样例（EXTICR 引脚路由 + MAPR 重映射/调试口配置）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.AFIO