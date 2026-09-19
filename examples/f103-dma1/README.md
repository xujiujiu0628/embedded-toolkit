# f103-dma1

DMA1 通道 1 内存到内存搬运最小样例（4 字 → 轮询 TCIF → 清标志）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.DMA1 (寄存器/位名见 main.c 各行 anchor)