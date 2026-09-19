# f103-timer-int-tim4

TIM4 10ms 更新中断最小样例 (WFI 休眠等中断)。

- 生成方式: gen_periph --type timer-int --timer TIM4 --period-ms 10
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.TIM4 (+ NVIC irq=30, ref.json _relationships)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
