# f103-crc

CRC 计算单元最小样例（复位→喂数→读结果）+ host mock 写序列断言。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 可测性: MOCK 哨兵 — `make test` 用 host gcc 跑寄存器序列/纯逻辑断言
- 寄存器数据来源: ref.json peripherals.CRC