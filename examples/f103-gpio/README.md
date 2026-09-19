# f103-gpio

PC13 推挽输出 2MHz 最小样例 — GPIOC CRH 位段配置 + BSRR/BRR 翻转。

- 生成方式: gen_periph --type gpio --pin PC13 --mode out-pp-2mhz
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.GPIOC (+ RCC.APB2ENR.IOPCEN)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
