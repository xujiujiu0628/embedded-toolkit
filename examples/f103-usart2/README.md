# f103-usart2

USART2 115200-8N1 轮询收发最小样例 (PA2=TX PA3=RX)。

- 生成方式: gen_periph --type usart --usart USART2 --baud 115200 --tx PA2 --rx PA3
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.USART2 (+ _relationships.USART2.pins: TX=A2 RX=A3)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
