# f103-dbg

DBGMCU 最小样例（基址/IDCODE 位域切分/DBGCR 调试保持位）+ host mock 断言。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 可测性: MOCK 哨兵 — `make test` 用 host gcc 跑 5 组断言（基址/偏移锚定、
  IDCODE 位域切分已知答案、DBGCR 位型手算 0x107 与 0x527、非法位防御、清零回读），
  对齐 f103-crc 水准（同为一组写序列 + 已知答案 + 边界防御）
- 寄存器数据来源: ref.json `peripherals.DBG`（base 0xE0042000；IDCODE@0x0
  DEV_ID 0:11 / REV_ID 16:31；CR@0x4 位名齐全）
- 位号第二源: `data/stm32f103-arch-facts.json` → `dbg.cr_bits`
  （逐条锚 `CMSIS:stm32f103xg.h:11100-11142` 的 `DBGMCU_CR_*_Pos`）
- 口径注记（只注不改）: ref.json `DBG.bus == "?"`（无 RCC 使能位可依）；
  DBG 无中断向量；`DBG_CAN2_STOP(bit21)` 在 ref.json 位表中存在但
  stm32f103xg.h 无对应锚点，样例按 ref.json 位表取掩码，未私改
- 补做理由: 一期（WB-20260919-04）"ref.json 无 DBGMCU 条目零数据可锚定"的
  理由失实（WB-20260920-02 勘误④），本样例为该项解锁件
