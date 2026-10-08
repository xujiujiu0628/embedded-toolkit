# f103-iwdg

IWDG 独立看门狗配置最小样例（解锁→PR/RLR→喂狗→启动）+ 超时换算可测。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: ✅ 2026-10-08 真机 PASS（F103C8T6 + ST-Link，SWD 回读判据）——PR=2/RLR=250 与配置逐位一致、4s 稳态无复位（IWDGRSTF=0）、停喂 500ms 触发 IWDGRSTF=1（活性实证）。注: openocd `stm32f1x.cfg` examine 会置 `DBGMCU_CR.DBG_IWDG_STOP`，活性测试须先清该位
- 可测性: MOCK 哨兵 — `make test` 用 host gcc 跑寄存器序列/纯逻辑断言
- 寄存器数据来源: ref.json peripherals.IWDG