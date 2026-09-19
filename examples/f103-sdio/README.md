# f103-sdio

SDIO 上电与时钟配置参考型样例（C8T6 无 SDIO；卡命令流程不在本样例范围）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.SDIO (注: available_on_c8=false; CLKCR/POWER 位域 ref.json)