# f103-spi3

SPI3 Mode0 /8 分频主模式参考型样例 — C8T6 无 SPI3 (高密度才有), 引脚与 JTAG 冲突需 AFIO 让位。

- 生成方式: gen_periph 不支持 SPI3 (GAP-G-1) — 主体 = SPI2 生成物 + 手工适配 (适配行均带 ref.json anchor)
- 硬件验收: 未做（编译级样例）
- ref.json anchor: RCC.APB1ENR.SPI3EN@15 (ref.json RCC); SPI3 基址/引脚见 GAPREPORT GAP-G-1
- 组装差异: GAP-G-1 手工适配体 (diff 见 main.c 头注与 GAPREPORT)
