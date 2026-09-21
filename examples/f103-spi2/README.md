# f103-spi2

SPI2 Mode0 /8 分频主模式最小样例 (软件 CS); write_burst 逐字节排空 RX
(F-178/H-3 已修 — 原 GAPREPORT GAP-S-1 注销)。

- 生成方式: gen_periph --type spi --spi SPI2 --spi-mode 0 --baud-div 8 --sck PB13 --miso PB14 --mosi PB15 --nss PB12
- 硬件验收: 未做（编译级样例）
- ref.json anchor: peripherals.SPI2 (+ _relationships.SPI2.pins: NSS=B12 SCK=B13 MISO=B14 MOSI=B15)
- 组装差异: 裸语句包入 init 函数; static 助手/ISR/_write 原文落文件作用域
