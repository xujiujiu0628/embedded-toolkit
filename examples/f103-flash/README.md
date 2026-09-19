# f103-flash

FLASH 只演示解锁/上锁时序与预取配置（不执行任何擦写，README 红字声明）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.FLASH (KEYR 魔数 GAP-D-4; ACR 2WS 来自 f103_known_issues.json Flash.wait_states)