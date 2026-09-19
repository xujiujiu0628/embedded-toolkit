# f103-i2c2

I2C2 100kHz 标准模式主发送最小样例 (PB10=SCL PB11=SDA), 含错误链。

- 生成方式: gen_periph --type i2c --i2c I2C2 --speed 100000 --scl PB10 --sda PB11
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.I2C2 (+ _relationships.I2C2.pins: SCL=B10 SDA=B11)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
