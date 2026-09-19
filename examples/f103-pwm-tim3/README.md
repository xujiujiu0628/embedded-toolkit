# f103-pwm-tim3

TIM3 CH1 (PA6) 1000Hz 50% 占空比 PWM 输出最小样例。

- 生成方式: gen_periph --type pwm --timer TIM3 --ch 1 --freq 1000 --duty 50
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.TIM3 (+ _relationships.TIM3.pins / RCC.APB1ENR.TIM3EN)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
