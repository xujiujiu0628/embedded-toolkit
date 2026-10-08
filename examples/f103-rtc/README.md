# f103-rtc

RTC 配置链最小样例（DBP→LSE→RTCSEL/RTCEN→CNF 进配置→1Hz→轮询秒标志）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: ✅ 2026-10-08 真机 PASS（F103C8T6 + ST-Link；先红后绿：buggy 版 BDCR=0x8203=RTCSEL 10b=LSI 且 RTC 停摆（CNT/DIV 冻结、RSF=0）→ F-223 修复 RTCSEL=01b 后 BDCR=0x8103、CRL RSF/RTOFF=1、CNT 10 秒 +10 = 1Hz）
- 寄存器数据来源: ref.json peripherals.RTC (+ RCC.BDCR 位名, PWR.CR.DBP, BKP 基址口径 GAP-D-2)