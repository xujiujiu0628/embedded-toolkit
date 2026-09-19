# f103-i2c1

I2C1 100kHz 标准模式主发送最小样例 (PB6=SCL PB7=SDA), 含错误链。

- 生成方式: gen_periph --type i2c --i2c I2C1 --speed 100000 --scl PB6 --sda PB7
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.I2C1 (+ _relationships.I2C1.pins: SCL=B6 SDA=B7)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
