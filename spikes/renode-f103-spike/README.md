# Renode 跑 STM32F103 — 阶段 1 + 2a + 2b（2026-11-18）

结论：**boot 通、主循环在跑、bit-band 已补**。剩下的缺口是 GPIO 输入与软 I2C 从设备。

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

```bash
cd D:/toolchains/renode/renode_1.17.0-portable
./renode.exe --disable-gui -P -1 \
  "D:/claude-embed/embedded-toolkit/spikes/renode-f103-spike/boot.resc"
```

`-P -1` 下 monitor 命令**不回显**（`echo`、`sysbus.cpu PC` 都看不到）。要取值走 `--console`：

```bash
printf '%s\n' \
 'mach create "a"' \
 'machine LoadPlatformDescription @D:/claude-embed/embedded-toolkit/spikes/renode-f103-spike/stm32f103-dwt.repl' \
 'sysbus LoadELF @D:/claude-embed/hw-projects/stm32f103-mpu6050-oled/build/mpu6050-oled.elf' \
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

## 仍然缺的

| 缺口 | 影响 | 补法 | 估时 |
|---|---|---|---|
| **GPIO 输入** | 按键恒 0 → 假按键事件（见上） | 需要能驱动 `IDR` 的手段；monitor 没有 `gpioPortX` 命令，可能得用 Python 外设替掉 `GPIOPort` 或写 GPIO 连接件 | 1 天 |
| **RCC 时钟位** | `__HAL_RCC_*` 写不落盘（读由 SVD Tag 假供值） | 写一个 RCC Python 桩，维护 CR/CFGR/APBxENR 位并提供"ready"位 | 半天 |
| **软 I2C 从设备** | MPU6050/OLED 无应答，`init FAIL` | 给 PB8/9、PB10/11 挂状态机外设 | 1~2 天 |

## 边界

这是 **L1 预检**，永远不升级成验收：电气层、上电时序、真实外设的非理想行为都测不到。
在有 GPIO 输入模型之前，任何依赖按键/传感器的仿真结论都不能采信。
