# F-149 C-1 spike — qemu-system-arm 跑 STM32F103 (stm32vldiscovery)

结论: **GO**（qemu-system-arm + semihosting 为 sim 后端主方案; 见
CHANGELOG F-149）。本目录是可回放的 spike 现场, 不入 CI、不属于运行时工具。

## 环境

- QEMU 11.1.0（Windows: winget `SoftwareFreedomConservancy.QEMU`;
  Ubuntu CI: `apt-get install qemu-system-arm`）
- arm-none-eabi-gcc 10.3.1

## 三个实验

```bash
# 构建 (semihosting 版)
arm-none-eabi-gcc -mcpu=cortex-m3 -mthumb -O0 -ffreestanding -nostdlib \
  -T link.ld main.c -o fw.elf

# 实验 B: SYS_EXIT_EXTENDED 正常退出 (推荐形态)
arm-none-eabi-gcc ... -DUSE_EXIT_EXTENDED=1 main.c -o fw_ext.elf
qemu-system-arm -M stm32vldiscovery -kernel fw_ext.elf -nographic \
  -semihosting-config enable=on,target=native -no-reboot
# → 全文打到 stderr, qemu 进程干净退出

# 实验 A: 旧 SYS_EXIT(0x18) — qemu 无声忽略, 进程不退出 (外部 timeout kill
# 后部分输出仍完整可采) —— M-profile 必须用 SYS_EXIT_EXTENDED(0x20)

# 实验 C: USART1 直写 (main_usart.c, 无 semihosting)
arm-none-eabi-gcc ... main_usart.c -o fw_usart.elf
qemu-system-arm -M stm32vldiscovery -kernel fw_usart.elf -nographic -monitor none
# → USART1 DR 直写转发到 stdout (qemu 不 gate RCC 时钟位)
```

## 实测记录（QEMU 11.1.0, Windows x64, 2026-09-12）

| 实验 | 收尾 | 输出通道 | qemu 行为 |
|---|---|---|---|
| A `fw.elf` | SYS_EXIT(0x18)+自旋 | stderr 全文 | **不退出**, 外部 kill, 输出完整 |
| B `fw_ext.elf` | SYS_EXIT_EXTENDED(0x20) | stderr 全文 | 干净退出 |
| C `fw_usart.elf` | 自旋 | **stdout** 全文 | 外部 kill, 输出完整 |

判定链启示: printf 全文采集（含 TGL/数值样例）两条通道都通; 超时路径
部分输出可采（对齐 F-003 归因纪律）; `sim` 证据恒 `simulation_validated`
（F-146），不进发布门禁。
