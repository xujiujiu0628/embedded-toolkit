# f103-usart3

USART3 115200-8N1 轮询收发最小样例 (PB10=TX PB11=RX)。

- 生成方式: gen_periph --type usart --usart USART3 --baud 115200 --tx PB10 --rx PB11
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.USART3 (+ _relationships.USART3.pins: TX=B10 RX=B11)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
