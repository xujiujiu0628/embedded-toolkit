# f103-can

bxCAN 初始化时序最小样例（INRQ 进初始化→BTR 位时序→出初始化）+ 波特率换算可测。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: ✅ 2026-10-08 真机 PASS（F103C8T6 + ST-Link；先红后绿：buggy 版 MCR 停 0x10003、INAK=1 永不完成、BTR 复位值未动 → F-223 修复 INAK 位号（bit0）后 MCR=0x1001A、INAK=0、BTR=0x005A0003=500kbps 配置）。范围=初始化时序（收发/总线伙伴未验）；终态 SLAK=1（进入 Sleep——MCR.SLEEP 为复位默认、样例未退出，最小样例范围内登记）
- 寄存器数据来源: ref.json peripherals.CAN (引脚映射 ref.json 未登记 — GAP-D-4, 本样例只配核心寄存器)