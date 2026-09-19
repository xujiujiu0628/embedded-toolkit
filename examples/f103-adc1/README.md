# f103-adc1

ADC1 CH0 (PA0) 单次软件触发采样最小样例, 含 mv 换算。

- 生成方式: gen_periph --type adc --adc ADC1 --ch 0 --pin PA0
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.ADC1 (+ _relationships.ADC1.pins: CH0=A0)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
