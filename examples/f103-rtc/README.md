# f103-rtc

RTC 配置链最小样例（DBP→LSE→RTCSEL/RTCEN→CNF 进配置→1Hz→轮询秒标志）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.RTC (+ RCC.BDCR 位名, PWR.CR.DBP, BKP 基址口径 GAP-D-2)