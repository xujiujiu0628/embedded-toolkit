# f103-wwdg

WWDG 窗口看门狗配置最小样例（CR/CFR）+ 窗口刷新判定纯函数可测。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 可测性: MOCK 哨兵 — `make test` 用 host gcc 跑寄存器序列/纯逻辑断言
- 寄存器数据来源: ref.json peripherals.WWDG