# f103-timer-int-tim2

TIM2 10ms 更新中断最小样例 (WFI 休眠等中断)。

- 生成方式: gen_periph --type timer-int --timer TIM2 --period-ms 10
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.TIM2 (+ NVIC irq=28, ref.json _relationships)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
