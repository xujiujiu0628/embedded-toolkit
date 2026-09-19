# f103-pwr-bkp

PWR/备份域合并样例（DBP 解锁→BKP 备份寄存器写入/读回，42 个 DR 演示前 4 个）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.PWR / BKP (DR1 绝对地址 = 0x40006C00+0x04, 口径注记 GAP-D-2)