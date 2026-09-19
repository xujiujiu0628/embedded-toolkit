# f103-usart1

USART1 115200-8N1 轮询收发最小样例 (PA9=TX PA10=RX), 含 _write 重定向。

- 生成方式: gen_periph --type usart --usart USART1 --baud 115200 --tx PA9 --rx PA10
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.USART1 (+ _relationships.USART1.pins: TX=A9 RX=A10)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
