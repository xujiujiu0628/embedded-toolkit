# Renode 跑 STM32F103 — 阶段 1 / 2a / 2b / 2c（2026-11-18）

结论：**boot 通、主循环在跑、bit-band 与 GPIO 输入已补**。软 I2C 从设备在 Renode 1.17 上撞到架构限制，见最后一节。

本目录是可回放的 spike 现场，**不入 CI、不属于运行时工具**。

## 环境

- Renode **1.17.0**（Windows portable，`D:\toolchains\renode\renode_1.17.0-portable`）
- 被测固件：`hw-projects/stm32f103-mpu6050-oled/build/mpu6050-oled.elf`（`-g -gdwarf-2`）

## 文件

| 文件 | 作用 |
|---|---|
| `stm32f103-dwt.repl` | 原厂 F103 平台 + `BitBanding` + DWT 计数桩 |
| `boot.resc` | 建机器 → 载平台 → LoadELF → 跑 2 秒 |

## 运行

> 命令里的 `<d-claude-root>` 是本机工作区根的占位（仓内禁写裸机器路径，
> 见 `tests/test_source_hygiene_paths.py`），实际执行前替换成你的路径。

```bash
cd D:/toolchains/renode/renode_1.17.0-portable
./renode.exe --disable-gui -P -1 \
  "<d-claude-root>/embedded-toolkit/spikes/renode-f103-spike/boot.resc"
```

`-P -1` 下 monitor 命令**不回显**（`echo`、`sysbus.cpu PC` 都看不到）。要取值走 `--console`：

```bash
printf '%s\n' \
 'mach create "a"' \
 'machine LoadPlatformDescription @<d-claude-root>/embedded-toolkit/spikes/renode-f103-spike/stm32f103-dwt.repl' \
 'sysbus LoadELF @<d-claude-root>/hw-projects/stm32f103-mpu6050-oled/build/mpu6050-oled.elf' \
 'start' 'sleep 3' 'sysbus.cpu PC' 'quit' \
 | ./renode.exe --console --disable-gui
```

## 三段实测

| 阶段 | 改动 | 唯一 PC | 卡在 |
|---|---|---|---|
| 1 | 原厂平台 | 22 | `0x08001FE4` `i2c_delay_us`（`mpu6050_i2c.c:31`）——DWT 缺失，延时死循环 |
| 2a | + DWT 计数桩 | 51 | 初始化全部走完，进 `while(1)` |
| 2b | + BitBanding | 54 | 同上；`0x42420060` 未映射写消失 |

2b 之后全量日志里只剩一处未映射外设：`0x40021000`（RCC）被写 5 次——SVD `Tag` 只供读值，
写仍然落空。所以 **RCC 时钟使能在这套仿真里依旧是空操作**，只是不再伪装成"写到了别处"。

### DWT 桩

```
dwt: Python.PythonPeripheral @ sysbus 0xE0001000
    size: 0x1000
    script: '''
if request.IsInit:
    cyccnt = 0
elif request.IsRead:
    if request.Offset == 0x4:
        cyccnt = (cyccnt + 144) & 0xFFFFFFFF
        request.Value = cyccnt
    else:
        request.Value = 0
elif request.IsWrite:
    if request.Offset == 0x4:
        cyccnt = request.Value & 0xFFFFFFFF
'''
```

每读一次 CYCCNT 前进 144 tick（= 2µs @72MHz，工程的 I2C 位延时档）。**让忙等收敛的桩，
不是周期精确模型。**

### bit-band

```
peripheral_bb: Miscellaneous.BitBanding @ sysbus <0x42000000, 0x43FFFFFF>
    peripheralBase: 0x40000000
```

效果：`0x42420060`（= `0x42000000 + (0x40021000-0x40000000)*32 + 0x60`，`RCC_CR` 的位带
别名）不再报未映射，`HAL_RCC_OscConfig` 的位带写被正确折算到 `0x40021000`。

## RTT 输出（从 RAM 直接读，不需要调试器）

`_SEGGER_RTT` = `0x2000077C`，up buffer = `0x200007D4`（`arm-none-eabi-nm` 查）。
命令：`sysbus ReadBytes 0x200007D4 512`，解出 638 字节：

```
[BOOT] stm32f103-mpu6050-oled v0.1
[BOOT] MPU6050 init FAIL
[IR] init pin=PB12
[IR] mode=MPU
[BRT] adc init FAIL (brightness off-line)
[BOOT] MAX7219 init rc=0
[BOOT] MAX7219 selftest: 1 row @low (0.3s)
[BOOT] PB15 long = recalibrate gyro
[BOOT] TETRIS page 3: tilt=move tap=rotate/restart
[DIAG] MPU6050_UpdateEuler FAIL
[STATE=0 last=0] ax=0.00 ... cur=0 next=6
[CAL] FAIL
[KEY] PB15 long: tetris restarted
[DIAG] PA0=0 (1=high=pressed)
```

`MPU6050 init FAIL` / `[CAL] FAIL` / 传感器全 0 是**预期**的（没有 I2C 从设备），恰好证明
执行真的到了依赖外设那一步。

**`[KEY] PB15 long: tetris restarted` 是假事件**：GPIO 输入未建模、读回恒 0，按键状态机
把它当成了边沿。这类"看起来合理、实际没发生"的输出是仿真最危险的一面。

## `.repl` 格式的三个坑（踩过，别再踩）

1. **不支持 `#` 注释**。原厂 290 行平台文件里零条注释。加任何注释行（中文或英文）都会让
   解析静默卡死——进程挂到 timeout，无任何错误输出。
2. **多行 `'''` 脚本必须是最后一个外设声明**。它后面再接带范围的声明（`@ sysbus <0x..,0x..>`）
   同样卡死。
3. **`Miscellaneous.DWT` 在 1.17.0 里不存在**（递归搜所有 DLL 零命中），
   `platforms/cpus/imxrt500.repl` 里那行引用是坏的。要 DWT 只能自己搭 Python 桩。

排查这些时唯一可靠的信号是"进程超时 + 日志停在 `System bus created`"——Renode 不会报错。

## 阶段 2c：GPIO 输入（按键假事件已消除）

`Miscellaneous.Button` 可直接驱动 GPIO 输入线，按工程极性表接：

```
Key0: Miscellaneous.Button @ gpioPortA
    -> gpioPortA@0

Key1: Miscellaneous.Button @ gpioPortB
    invert: true
    -> gpioPortB@15
```

- KEY0 = PA0 **高电平按下**（`key.c:29`，下拉）→ 不 invert，空闲=低
- KEY1 = PB15 **低电平按下**（`key.c:30`，上拉）→ `invert: true`，空闲=高

效果：`[KEY] PB15 long: tetris restarted` 这条**假事件消失**，`[DIAG] PA0=0` 保持 0
（与真机空闲态一致）。这是本项目里第一个"仿真输出不再撒谎"的检查点。

## 阶段 3：C# 外设可行性（已验到一半）

.NET SDK 8.0.428 装在 `D:/toolchains/dotnet`（用户级，未改系统 PATH）。

已验证（可复现）：

1. **Renode 自带 Roslyn**，`include @xxx.cs` 能直接编译 C# 源码并加载，不需要预编译 dll。
2. **插件类契约**：`[Plugin(Name=..., Version=..., Description=..., Vendor=...)]` +
   构造函数收 `Monitor` + 实现 `IDisposable`。没有 `IPlugin` 接口。
3. **外设类型能被平台描述解析**，但要同时满足三条，缺一不可：
   - 命名空间在 `knownDirectories` 内（用 `Antmicro.Renode.Peripherals.Miscellaneous` 实测通过）；
   - 类**直接**实现 `IPeripheral`（`AnalyzeAssembly` 只看直接接口，不认 `IDoubleWordPeripheral` 的间接继承）；
   - 平台描述里用**全限定名**：`p: Antmicro.Renode.Peripherals.Miscellaneous.XxxPeriph @ sysbus 0x...`，短名会报 `E04 Could not resolve type`。

```csharp
[Plugin(Name = "probe", Description = "plumbing probe", Version = "0.1", Vendor = "local")]
public sealed class ProbePlugin : IDisposable
{
    public ProbePlugin(Monitor monitor) { }
    public void Dispose() { }
}

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class ProbePeriph : IPeripheral, IDoubleWordPeripheral, IKnownSize
    {
        public long Size { get { return 0x10; } }
        public uint ReadDoubleWord(long offset) { return 0xDEADBEEF; }
        public void WriteDoubleWord(long offset, uint value) { }
        public void Reset() { }
    }
}
```

实测输出（`peripherals` 命令）：

```
p (ProbePeriph)  <0xE00FD000, 0xE00FD00F>
```

### GPIO 接线：接收通了，发送未通

**接收方向（端口通知外设）可用**。把线加进平台里已有的 `gpioPortB` 连接块：

```
gpioPortB:
    10 -> timer2@02 | rxprobe@0
    11 -> timer2@03 | rxprobe@1
...
rxprobe: Antmicro.Renode.Peripherals.Miscellaneous.RxProbe @ gpioPortB
```

加载后立刻收到回调（实测）：

```
GPIO-IN number=1 value=False
GPIO-IN number=0 value=False
```

**发送方向（外设拉线）未通**，三种写法各撞一个错：

| 写法 | 结果 |
|---|---|
| `@ gpioPortB 11` + `-> gpioPortB@11`（同时实现收/发） | `E37`：该注册点上 IGPIOReceiver 与 IGPIOSender 二义，无法决定注册哪一种 |
| 去掉编号 `@ gpioPortB` + `-> gpioPortB@11` | `E13 Type '...' does not contain any property of type GPIO` —— `->` 要求目标上有一个**类型为 `GPIO` 的属性**（多个时需 `[DefaultInterrupt]` 标注），`IGPIO State` 不算 |
| 补上 `[DefaultInterrupt] public GPIO Line` 后接发送线（不含 `|` 多目标） | 仍然抛 `NullReferenceException`（`CreationDriver.HandleError` 内部，错误处理器自己崩了——真实错误被自己的报错路径吃掉） |
| 只接发送、不做接收（最小组合） | 同上，`NullReferenceException` |

最后一条意味着 **`.repl` 的连线语法对"同一引脚挂多个接收者 + 自定义发送者"这种组合不可用**，不是我们写法问题。

**下一步（已定位到 API）**：`IGPIO.Connect(IGPIOReceiver destination, int number)` 存在，
可以在插件里程序化接线——插件构造拿到 `Monitor`，在机器创建后把自建 `GPIO`
连到 `gpioPortB` 的 11 脚，绕开 `.repl` 解析器。这条路还没验证。

### 程序化接线：通了

`.repl` 连线走不通，但**从 IronPython 里接**可以，且不碰解析器：

```
python "port = monitor.Machine['sysbus.gpioPortB']"
python "from Antmicro.Renode.Core import GPIO"
python "g = GPIO(); g.Connect(port, 11)"
python "g.Set(True)"   → sysbus ReadDoubleWord 0x40010C08 = 0x00000800
python "g.Set(False)"  → sysbus ReadDoubleWord 0x40010C08 = 0x00000000
```

要点：`Machine['gpioPortB']` 找不到，必须写 `Machine['sysbus.gpioPortB']`；
`IGPIO.Connect(IGPIOReceiver, pin)` 建立驱动。

**端口语义实测**：IDR 直接跟随接入的 GPIO 值（外接 true → IDR 1，外接 false → IDR 0），
**与自身 ODR 无关**——不是开漏的线与，是覆盖。对 I2C 来说这意味着从机一旦持有
SDA，主控就"看不见"自己的驱动，需要额外处理（见下）。

### MPU6050 从机模型

`cs/mpu6050_slave.cs`：地址 0x68、WHO_AM_I=0x68、寄存器可读写，实现
`IPeripheral, IGPIOReceiver, IDoubleWordPeripheral, IKnownSize`（**必须有总线接口**，
否则 `@ sysbus 0x...` 报 `E21 没有合适的构造函数`）。接收方向接线在平台里：

```
gpioPortB:
    10 -> timer2@02 | mpu@0
    11 -> timer2@03 | mpu@1
mpu: Antmicro.Renode.Peripherals.Miscellaneous.Mpu6050Slave @ sysbus 0xE00FD200
```

实测进展（2026-11-18 末）：

1. 平台能加载，从机收到引脚变化；
2. **固件的 I2C 位流被正确解出**——从机打印：

```
SLAVE start
SLAVE byte 0xD0 st=1     ← 写地址 (0x68<<1 | 0)
SLAVE start
SLAVE byte 0xD2 st=1     ← 读地址 (0x68<<1 | 1)
```

说明 SCL/SDA 采样、起始条件识别、8 位移位全部正确。

3. **但 ACK 没被主控看见**：地址之后就没有后续字节，固件仍报 `MPU6050 init FAIL`。
   已排除：ACK 在第 8 个时钟下降沿就被释放（改成分两拍持有，仍未解决）。
   当前怀疑 `Sda.Disconnect()/Connect()` 的重新挂接在事务中不生效，或端口在
   OD 模式下的 IDR 合成方式与预期不同。

### ACK 可见性排查记录（未解决）

沿程序化接线继续推，得到的事实：

- 从机收到的地址帧是 **0xD0 / 0xD2**，位级采样正确；
- `Acknowledge()` **确实被调用**（加打印确认），但主控随后**重发 START** →
  说明它读到的是 NACK；
- 已排除 ACK 提前释放：改成"第 8 时钟驱动、第 9 时钟保持、之后释放"的两拍逻辑，现象不变；
- 已排除 `Connect/Disconnect` 时序：Renode 源码注释明写 `IGPIO.Connect`
  **不可在运行中使用**（"may lead to nondeterminism"），所以改成**启动时连一次、之后只 `Set`**；
- 已排除"主控释放 SDA 覆盖我们的低电平"：在 `OnSda` 里检测到主控拉高就重新压低，现象不变。

**已证实的根因（2026-11-19）**：读回固件跑起来后的寄存器 ——

```
CRL = 0x00000000   CRH = 0x80087777   IDR = 0x00008C00   ODR = 0x00008C00
```

PB10/PB11 的 CRH nibble 是 `0b0111`（开漏输出 50MHz）。按这个 CRH 复现 IDR 语义：

| 外部驱动 | IDR |
|---|---|
| `Set(False)` | `0x00000800`（仍等于 ODR） |
| `Set(True)` | `0x00000800` |

**结论：引脚一旦被配置成输出，IDR 就跟随 ODR，外部驱动完全不可见**——之前
"外接驱动决定 IDR"的结论只在**输入模式**（默认 `CRH=0x44444444`）下成立。
这就是 ACK 不可见的根因，不是时序问题。

**试过的绕过（失败）**：让从机直接写 `BSRR/BRR` 去改 ODR（既然 IDR 跟 ODR）。
结果采样被自己的写污染（地址帧从 `0xD0` 变成 `0x10`，说明高位被自己的 ODR
写覆盖）；加上"自写屏蔽"后固件直接卡死在启动（RTT 全 0）。已回退到能解帧的版本。

另一条（更稳）的思路：把从机做成**替换 `gpioPortB` 的模型**，自己实现
BSRR/ODR/IDR 与开漏线与语义，代价是要把 EXTI/TIM/DMA 那 20+ 处引用接回来。

## 仍然缺的

| 缺口 | 状态 | 说明 |
|---|---|---|
| **软 I2C 从设备** | **卡住（架构限制）** | MPU6050/OLED 仍无应答，`MPU6050 init FAIL` 是预期 |
| **RCC 时钟位** | 不做 | `__HAL_RCC_*` 写不落盘，但 Renode 的外设模型不检查时钟使能，补了也不改变行为；读值由 SVD `Tag` 供 |

### 为什么软 I2C 从设备卡住

要模拟 bit-bang I2C，必须能**观察并驱动 GPIO 线电平**。当前器材里没有这条路：

1. **Python 外设接不了 GPIO**：声明 `Python.PythonPeripheral @ sysbus ...` 再加
   `-> gpioPortB@10`，Renode 1.17 静默卡死（和 `.repl` 解析坑同一症状）。
   对照实验：`Miscellaneous.Button` 用同样写法能加载并生效，说明不是语法问题，
   而是 Python 外设不实现 GPIO 接收/驱动接口。
2. **替换 `gpioPortB` 也不行**：原厂平台里 `gpioPortB` 被 EXTI、TIM1/2/3/4、
   DMA 等 20+ 处引用（`stm32f103.repl:187-245`），整块替掉会让这些连接全部失效，
   平台直接解析失败。
3. 因此只有两条真路：写一个实现 Renode GPIO 接口的 **C# 外设**（需编译进 Renode），
   或等上游支持 Python 外设挂 GPIO。

在补齐之前，**任何依赖 MPU6050/OLED 读回的仿真结论都不能采信**。

## 边界

这是 **L1 预检**，永远不升级成验收：电气层、上电时序、真实外设的非理想行为都测不到。
按键输入已有模型；在补上 I2C 从设备之前，任何依赖 MPU6050/OLED 读回的仿真结论都不能采信。
