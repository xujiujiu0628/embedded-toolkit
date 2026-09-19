# f103-systick

SysTick 1kHz 节拍 + delay_ms 最小样例 (100ms 心跳)。

- 生成方式: gen_periph --type systick --freq 1000
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.SysTick (Cortex-M3 核心; CTRL 位与生成器契约同源)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
