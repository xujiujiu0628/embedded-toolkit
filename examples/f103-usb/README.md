# f103-usb

USB 48MHz 时钟配置链参考型样例（仅 PLL→SW→USBPRE 时钟链；C8T6 的 USB 需外部 D+ 上拉）。

- 生成方式: 手写（寄存器级裸偏移, 逐项锚定 data/stm32f103-ref.json；无 HAL/LL/CMSIS）
- 硬件验收: 未做（编译级样例）
- 寄存器数据来源: ref.json peripherals.RCC (CR/CFGR 位名 ref.json; USBEN@APB1ENR bit23; PLL 编码表 GAP-D-4)