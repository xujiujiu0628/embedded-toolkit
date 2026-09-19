# f103-spi1

SPI1 Mode0 /8 分频主模式最小样例 (软件 CS), 已知 write_burst 不排空 RX (见 GAPREPORT GAP-S-1)。

- 生成方式: gen_periph --type spi --spi SPI1 --spi-mode 0 --baud-div 8 --sck PA5 --miso PA6 --mosi PA7 --nss PA4
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.SPI1 (+ _relationships.SPI1.pins: NSS=A4 SCK=A5 MISO=A6 MOSI=A7)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
