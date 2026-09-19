# f103-adc2

ADC2 CH0 (PA0) 单次软件触发采样最小样例。

- 生成方式: gen_periph --type adc --adc ADC2 --ch 0 --pin PA0
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.ADC2 (注: _relationships 无 ADC2 引脚条目, CH0=PA0 通用)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
