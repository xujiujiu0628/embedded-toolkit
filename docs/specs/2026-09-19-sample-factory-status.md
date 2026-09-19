# F103 外设样例工厂 — 状态表与 GAPREPORT（WB-20260919-04）

> 任务：`D:\wordbuddy\embedded-toolkit_样例工厂简报_WB-20260919-04.md`
> 基线：`c0df0c6`（v0.6）→ 分支 `wb/f103-sample-factory-20260919`
> 执行：Z code 定向 Executor，2026-09-19
> 核对：`python -m unittest tests.test_sample_factory` → **Ran 47 tests OK**
> （40 样例 + 7 mock 子项）；全量 `python -m unittest discover -s tests`
> → **Ran 953 tests OK (skipped=6)**（906 基线 + 47 新增，6 skip 均为既有
> coverage 包未装/真档冒烟 opt-in，与本任务无关）

## 一、逐样例状态表

图例：tier = 简报分层；来源 = gen_periph 生成体 / 手写；编译 = `make all`
rc=0 且 ELF+HEX 产出（工厂巡检测试断言）；mock = 目录含 `MOCK` 哨兵且
`make test`（host gcc）断言全过。

| # | 目录 | tier | 来源 | 编译 | mock |
|---|---|---|---|---|---|
| 1 | f103-gpio | T1 | gen_periph `--type gpio --pin PC13 --mode out-pp-2mhz` | ✅ | — |
| 2 | f103-usart1 | T1 | gen_periph `--type usart --usart USART1 --baud 115200 --tx PA9 --rx PA10` | ✅ | — |
| 3 | f103-usart2 | T1 | gen_periph `--type usart --usart USART2 --baud 115200 --tx PA2 --rx PA3` | ✅ | — |
| 4 | f103-usart3 | T1 | gen_periph `--type usart --usart USART3 --baud 115200 --tx PB10 --rx PB11` | ✅ | — |
| 5 | f103-pwm-tim2 | T1 | gen_periph `--type pwm --timer TIM2 --ch 1 --freq 1000 --duty 50` | ✅ | — |
| 6 | f103-pwm-tim3 | T1 | gen_periph `--type pwm --timer TIM3 --ch 1 --freq 1000 --duty 50` | ✅ | — |
| 7 | f103-pwm-tim4 | T1 | gen_periph `--type pwm --timer TIM4 --ch 1 --freq 1000 --duty 50` | ✅ | — |
| 8 | f103-adc1 | T1 | gen_periph `--type adc --adc ADC1 --ch 0 --pin PA0` | ✅ | — |
| 9 | f103-adc2 | T1 | gen_periph `--type adc --adc ADC2 --ch 0 --pin PA0` | ✅ | — |
| 10 | f103-systick | T1 | gen_periph `--type systick --freq 1000` | ✅ | — |
| 11 | f103-timer-int-tim2 | T1 | gen_periph `--type timer-int --timer TIM2 --period-ms 10` | ✅ | — |
| 12 | f103-timer-int-tim3 | T1 | gen_periph `--type timer-int --timer TIM3 --period-ms 10` | ✅ | — |
| 13 | f103-timer-int-tim4 | T1 | gen_periph `--type timer-int --timer TIM4 --period-ms 10` | ✅ | — |
| 14 | f103-i2c1 | T1 | gen_periph `--type i2c --i2c I2C1 --speed 100000 --scl PB6 --sda PB7` | ✅ | — |
| 15 | f103-i2c2 | T1 | gen_periph `--type i2c --i2c I2C2 --speed 100000 --scl PB10 --sda PB11` | ✅ | — |
| 16 | f103-spi1 | T1 | gen_periph `--type spi --spi SPI1 --spi-mode 0 --baud-div 8 --sck PA5 --miso PA6 --mosi PA7 --nss PA4` | ✅ | — |
| 17 | f103-spi2 | T1 | gen_periph `--type spi --spi SPI2 --spi-mode 0 --baud-div 8 --sck PB13 --miso PB14 --mosi PB15 --nss PB12` | ✅ | — |
| 18 | f103-spi3 | T1 | gen_periph **不支持 SPI3**（GAP-G-1）— 主体 = SPI2 生成物手工适配，适配点三处均锚定 ref.json | ✅ | — |
| 19 | f103-dma1 | T2 | 手写（mem2mem + TCIF 轮询） | ✅ | — |
| 20 | f103-exti | T2 | 手写（PA0 上升沿 + ISR 清挂起） | ✅ | — |
| 21 | f103-iwdg | T2 | 手写（解锁→PR/RLR→喂狗→启动） | ✅ | ✅ 超时换算 + 写序列 |
| 22 | f103-wwdg | T2 | 手写（CR/CFR + 窗口刷新判定） | ✅ | ✅ 窗口语义 + 写序列 |
| 23 | f103-crc | T2 | 手写（复位→喂数→读结果） | ✅ | ✅ 写序列断言 |
| 24 | f103-dac | T2 | 手写（PA4 软件触发输出） | ✅ | ✅ mv→code 换算 + 写序列 |
| 25 | f103-can | T2 | 手写（INRQ 进出初始化 + BTR 位时序） | ✅ | ✅ 位时序换算 |
| 26 | f103-rtc | T2 | 手写（DBP→LSE→RTCSEL/RTCEN→CNF→1Hz） | ✅ | — |
| 27 | f103-afio | T2 | 手写（EXTICR 路由 + MAPR 重映射/SWJ_CFG） | ✅ | — |
| 28 | f103-nvic | T2 | 手写（ISER/ICER/IP，以 TIM2 IRQ 为例） | ✅ | — |
| 29 | f103-pwr-bkp | T2 | 手写（DBP→备份寄存器写读） | ✅ | — |
| 30 | f103-flash | T2 | 手写（仅解锁/上锁时序 + ACR 预取；**不执行擦写**） | ✅ | — |
| 31 | f103-tim1 | T2 | 手写（互补输出 + break + MOE） | ✅ | — |
| 32 | f103-tim8 | T2 | 手写（TIM1 同模板，实例差异注记） | ✅ | — |
| 33 | f103-tim5 | T2 | 手写（通用定时器 PWM） | ✅ | ✅ 分频换算 + 写序列 |
| 34 | f103-tim6-7 | T2 | 手写（基本定时器双实例双周期） | ✅ | ✅ 分频换算 + 写序列 |
| 35 | f103-tim9-14 | T2 | 手写（TIM9 双通道 + TIM10 单通道实做，差异表见 README） | ✅ | — |
| 36 | f103-adc3 | T3 | 手写（单次转换核心配置） | ✅ | — |
| 37 | f103-gpiod-g | T3 | 手写（D~G 四端口合并） | ✅ | — |
| 38 | f103-usb | T3 | 手写（仅 48MHz 时钟配置链，按简报） | ✅ | — |
| 39 | f103-sdio | T3 | 手写（POWER/CLKCR 核心配置） | ✅ | — |
| 40 | f103-fsmc | T3 | 手写（BCR1/BTR1 存储块使能） | ✅ | — |

**未做**：简报 T3 清单中的 `dbg` — `data/stm32f103-ref.json` 无 DBGMCU 条目，
零数据可锚定（简报禁线：禁止凭文档记忆默写；对不上的记 GAPREPORT），
见 GAP-G-4。T1/T2 清单无缺项（T1 18/18、T2 17/17）。

## 二、共享件

- `examples/f103-common/f103_regs.h` — 裸偏移寄存器层（无 HAL/LL/CMSIS）：
  结构体/实例指针/位宏逐项锚定 ref.json；内建 gen_periph 生成体契约垫片
  （error_chain_t/ERR_PLAIN/ERR_OK，与 `tests/test_gen_syntax_smoke.py`
  STUB_HEADER 同源）；`F103_MOCK_<外设>` 按外设可选地把实例重定向到
  host 内存；`F103_SAMPLE_HOST_TEST` 置空 `__DSB()/__WFI()`。
- `examples/f103-common/startup.c` — 最小启动桩：data 拷贝 + bss 清零 +
  向量表（设备槽位逐项注明来源 [ref]=ref.json _relationships / [GAP-D-3]
  =ref.json 未登记槽位；未登记槽位填 0）+ 全部设备 IRQ weak alias。
- `examples/f103-common/link.ld` — 母本 sim-demo，映像改 C8T6 64K/20K。

## 三、T1 生成体组装差异声明（简报 §2 允许的"仅补壳"）

1. 生成体裸语句原样包进 `static void <name>_init(void)`（逐行原文，不改
   缩进/措辞）；
2. 生成体中的 static 函数、ISR（`void TIMx_IRQHandler` / `void
   SysTick_Handler`）、`#define SPIx_CS_*`、`#include <unistd.h>` 原样落
   文件作用域；
3. main 壳提供最小使用场景（调用全部生成 static 函数，避免 `-Werror
   unused`）；usart 样例场景含 RXNE 条件回读；
4. f103-spi3 例外（生成器不支持）：主体 = SPI2 真实生成物 + 三处手工
   适配（SPI3EN@15 / 基址 0x40003C00 / SWJ_CFG 让位 JTAG），diff 已在
   main.c 头注逐行声明；
5. spi1/spi2 生成体含 `write_burst` 不排空 RX 的已知问题（GAP-S-1，
   生成器缺陷不改生成体），样例场景注释声明。

## 四、GAPREPORT

### A. 生成器缺口（只列不改 gen_periph）

| 编号 | 内容 | 处置 |
|---|---|---|
| GAP-G-1 | `gen_periph --type spi` 仅支持 SPI1/SPI2，SPI3 报 `Unknown SPI peripheral`（SPI3 时钟位在 RCC.APB1ENR bit15=SPI3EN，ref.json RCC 数据已备而 gen-maps 无此键） | f103-spi3 以 SPI2 生成物手工适配；建议 gen-maps 补 SPI3 键 |
| GAP-G-2 | `gen_timer_int` 固定 PSC 设计在 `--period-ms 100` 时 ARR=99999 溢出 16 位报 ERROR（简报命令要点恰为 100ms） | 样例改 10ms（PSC=71/ARR=9999）；建议生成器增加 PSC 自动升档 |
| GAP-G-3 | `--type systick` 实参为 `--freq`，简报要点所写 `--period-ms 100` 被生成器静默忽略（两种调用同输出） | 样例用 `--freq 1000`；建议补参数白名单或接受 period-ms |
| GAP-G-4 | `--type adc` 必须显式 `--pin`（简报要点未写）；`--type doc` 错误路径 rc=0（`Error: ... not found` 当成功） | 样例已补 `--pin PA0`；doc rc=0 为 scripts 疑似缺陷（见 §五） |

### B. ref.json 数据问题（只列不改 data/**）

| 编号 | 内容 | 证据 | 样例侧处置 |
|---|---|---|---|
| GAP-D-5 | 外设条目 `bus` 字段与 RCC 使能位归属矛盾：TIM9 记 APB1 但 APB2ENR bit19=TIM9EN；TIM12/13/14 记 APB2 但 APB1ENR bits 6/7/8=TIM12/13/14EN | `data/stm32f103-ref.json` RCC.APB1ENR/APB2ENR 位名导出 | 一律以 RCC 位数据为准（f103-tim9-14、f103_regs.h 注释） |
| GAP-D-2 | BKP 条目 base=0x40006C04（DR1 记偏移 0），与"外设基址+寄存器偏移"惯例口径不一（RM 口径 base=0x40006C00, DR1@0x04） | ref.json peripherals.BKP | f103_regs.h 按 0x40006C00 表达、DR1=+0x04，绝对地址相等；结构体注释声明 |
| GAP-D-1 | NVIC 条目仅登记 ISER@0xE100；ICER/IABR/IP（架构定义）缺失 | ref.json peripherals.NVIC | startup/样例按架构常量使用并逐行注明 GAP-D-1 |
| GAP-D-3 | ref.json `_relationships` 仅 12 个外设有 IRQ 号（max=39）；EXTI0(6)/TIM1_BRK_TIM9(24)/TIM8 系(43/44/45)/TIM5(50)/TIM6(54)/TIM7(55)/RTC(3) 未登记 | ref.json IRQ 号全量导出 | startup.c 槽位逐项注明 [ref]/[GAP-D-3]；未登记槽位填 0 |
| GAP-D-4 | 以下数据 ref.json 未登记，样例需要：IWDG KR 魔数序列(0x5555/0xAAAA/0xCCCC) 与 LSI 40kHz、FLASH KEYR 魔数(0x45670123/0xCDEF89AB)、CRC 多项式与字序、PLL 编码表(0111→×9)与 USBPRE 值语义、SDIO PWRCTRL 值语义、CAN/ADC3/TIM5/TIM8/TIM9 引脚映射、TIM1 CH1N/BKIN 引脚、FSMC BCR/BTR 位名、SDIO/FSMC/DMA2 的可用引脚 | 各样例 main.c 行内 GAP 注记 | 凡用到处行内注明"GAP-D-4：架构常量/位名，ref.json 未登记"；不做静默默写 |

### C. scripts 疑似缺陷（本轮工厂视角新发现/印证，只列不改）

| 编号 | 严重度 | 内容 |
|---|---|---|
| GAP-S-1 | Medium | gen_periph 生成的 `spiN_write_burst` 只写不读 DR：RM0008 单缓冲语义下 RXNE/OVR 残留，后续 `spiN_transfer` 首字节读到陈旧数据且永不自愈（本次 T1 生成物再次实证；f103-spi1/2/3 README 已声明） |
| GAP-G-4（同上） | Medium | `--type doc` 错误路径 rc=0（`gen_periph.py:1037` 直接 print gen_doc 返回串）；机器消费方按 rc 判定把"外设不存在"当成功 |
| GAP-S-2 | Low | 生成 I2C 片段引用 `error_chain_t/ERR_PLAIN/ERR_OK` 但不发射任何定义（仓内契约由 test_gen_syntax_smoke stub 与本工厂 f103_regs.h 承接）；建议生成器自带或文档声明该契约 |

## 五、mock 加强件说明（简报 §2 mock 规则）

- 7 个样例带 `MOCK` 哨兵：iwdg / wwdg / crc / dac / can / tim5 / tim6-7。
- `make test` = host gcc `-DF103_MOCK_REGS -DF103_SAMPLE_HOST_TEST`
  （+ 每样例 `MOCK_DEFS` 选定重定向的外设实例）编译 main.c，运行断言，
  全过 `exit 0`（`@echo MOCK PASS`）。
- 结构约定：配置序列函数两态共用（target 写真寄存器 / host 写重定向
  结构）；纯逻辑换算函数（IWDG 超时、CAN 位时序、DAC 码值、定时器
  分频、WWDG 窗口）两态共用；`#ifndef F103_SAMPLE_HOST_TEST` 只包
  target 的 main()。
- 工厂测试 host gcc 解析链：PATH gcc/cc/clang → msys64 常见安装位；
  解析不到时 mock 子用例 skipTest（不算失败），make 同目录与 host gcc
  同目录会 prepend 进子进程 PATH（mingw cc1 依赖同目录 DLL，缺失即
  gcc 静默 exit 1）。

## 六、commit 台账（分支 wb/f103-sample-factory-20260919，未 push）

| commit | 内容 |
|---|---|
| 5e1c08b | T1a 地基（f103-common + f103-gpio 试点 + 工厂巡检测试） |
| 34583bf | T1b usart×3 / pwm×3 / timer-int×3 |
| 193e88e | T1c adc×2 / systick / i2c×2 / spi×2+spi3 适配 — T1 18/18 |
| f91b211 | T2a dma1/exti/iwdg/wwdg/crc/dac/can/rtc/afio |
| 97ba99e | T2b nvic/pwr-bkp/flash/tim1/tim8/tim5/tim6-7/tim9-14 — T2 17/17 |
| c7cf16a | T3 adc3/gpiod-g/usb/sdio/fsmc（dbg 不做已声明） |
