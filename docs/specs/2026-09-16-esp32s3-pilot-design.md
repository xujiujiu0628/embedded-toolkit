# ESP32-S3 最小闭环试点 — 设计文档

- 日期：2026-09-16
- 分支：`feat/esp32s3-pilot`（今日全部改动不入 master，验收合入另议）
- 状态：已落地 (2026-09-16, feat/esp32s3-pilot) — 真机双 PASS + 4 负路径 + 2 真机钓修 (410bdcb/b678fca); STM32 真机回归挂账 (ST-Link 失联), 见 plan 台账
- 前史：2026-08-25 路线图（multi-mcu-tooling-roadmap）、2026-09-04 因无板挂起（esp32-onboarding-deferred）；本文档为唤起落地

## 0. 已验证事实（2026-09-16 spike）

- 目标板：**ESP32-S3** QFN56 rev v0.2，双核 Xtensa + LP Core，240MHz，**8MB PSRAM / 16MB Flash**，COM3 USB 直连
- esptool v5.4.0 实机连通：`chip_id`/`flash-id`/`read-flash`/hard-reset 全通过，stub flasher 正常
- 板子烧录口与日志口同为 COM3（USB-CDC），单口闭环成立

## 1. 目标与非目标

**目标（一句话）**：在 `<d-claude-root>\esp32s3-hello` 工程内运行 `python <toolkit>/scripts/verify.py`，跑通 **build → flash → capture → verify** 全链路并 PASS。

**非目标（YAGNI，全部后置）**：WiFi/蓝牙、probe-rs 调试接入、xiaozhi-esp32 闭环、PSRAM 压测、panic 符号化完整解析、开源整理。

## 2. 工具链安装（环境层）

- ESP-IDF **v5.4.x**，git clone + `install.ps1`/`export` 方式，装到 `<d-claude-root>\vendor\esp-idf\`（工具链组件在其 `tools/` 或 `<d-claude-root>\vendor\esp-idf-tools\`，以 IDF 安装器实际布局为准）；优先国内镜像（dl.espressif.cn / gitee 镜像）
- 系统 Python 的 esptool pip 包为 spike 临时物，收尾卸载；烧录统一走 IDF 自带 esptool（单一版本源）
- `machine.json` 新增键（机器路径唯一合法源铁律）：
  - `"esp_idf_path"`：IDF 根目录
  - `"esp_tools_dir"`：esptool 等工具所在目录（若与前者重合可只留一键，实现时定）
- 不动现有键；STM32 路径零触碰

## 3. 试点工程（工程层）

```
<d-claude-root>\esp32s3-hello\
  CMakeLists.txt          # IDF 标准顶层
  sdkconfig.defaults      # 目标 esp32s3、PSRAM 等最小配置
  main\
    CMakeLists.txt
    hello_main.c          # 周期性 printf 标记行（expect 靶子）
  .workbench\
    config.json           # 见 §4 配置契约
```

- 工程薄配置 + 工具库分离模式与 STM32 三工程一致
- 顶层 `<d-claude-root>\README.md` 分类表加一行（hw-projects / 活跃）

## 4. verify.py 集成（工具层）

### 4.1 配置契约（.workbench/config.json）

```json
{
  "builder": "idf",
  "flash":  { "backend": "esptool", "port": "COM3" },
  "capture":{ "backend": "uart", "port": "COM3", "baudrate": 115200,
              "duration_sec": 15 },
  "verify": { "expect": ["..."] }
}
```

缺省值全部维持现状（builder=gcc、flash=openocd、capture=semihosting），**不配置 = 行为与今日完全一致**。

> **2026-09-18 I-3 勘误（终审#2）**：① 原示例 `verify.capture_timeout` 为死键——`resolve_capture_timeout` 实际认 `capture.duration_sec`（T6 台账裁决，hello 工程实配 15s），示例已订正。② §4.2 表 capture 行的复位参数终态为 `--after hard_reset`（esptool v4/v5 通吃下划线集，真机实证 b678fca）；§0 第 11 行 spike 连通记录系 pip-esptool-v5 现场史实，保留不改。③ plan 内的代码/测试原文（dash 形态）按执行档案保真，终态以本文件 + git 为准。

### 4.2 三个派发点（现状已核实）

| 位置 | 现状 | 新增 |
|---|---|---|
| `step_build`（verify.py:174） | `builder == "gcc"` / keil | `idf` 分支 → 调 esp_runtime 封装的 `idf.py build`，产物 .bin 路径写入 state.json `last_build` |
| `step_flash`（:217） | OpenOCD 直调 | 按 `flash.backend` 派发：openocd（默认，原路径）/ esptool → `esp_runtime.step_flash_esptool()` |
| capture 派发（:622，现 semihosting\|rtt\|sim） | if-elif | `uart` 分支 → 新 `esp_runtime.step_capture_uart()`：esptool `--after hard_reset` 复位 → 串口采集 N 秒 → 返回文本 |

### 4.3 esp_runtime.py（新文件，scripts/）

- `run_idf(cmd)`：以 `export` 环境（PowerShell profile 或 env 脚本）拉起 idf.py 子进程，超时/编码/退出码规范化
- `step_flash_esptool(bin_file, cfg)`：组装 `esptool --chip esp32s3 -p COM3 write_flash`（地址表由 idf.py flash 的 flash_args 或显式 offset 提供，实现时定，倾向复用 IDF 产物 `flash_args`）
- `step_capture_uart(cfg, timeout)`：复用 serial_log/serial_runtime 的连接骨架，含 mux 兼容
- panic 检测只做**文本级标记**：捕获文本含 `Guru Meditation` / `Backtrace:` / `abort()` → result 里 `esp_panic: true`，交给 judge；不做符号化

### 4.4 Analyze 降级策略

- IDF 构建日志：error 计数（正则 `error:` 行）+ 原始日志直通
- **不接** keil-error-db（ARMCC/GCC 条目对 xtensa 无意义，污染校准）
- `analyze.status` 语义与现状对齐：有 error → `error` 早退

### 4.5 设备锁

- uart/esptool 后端同样走 `hw_lease.acquire()`（F-145 契约不变，COM3 是互斥资源）
- sim_mode 判定不受影响（`cap_backend == "sim"` 才免锁）

## 5. 测试策略

### 5.1 host 单测（编码完成门槛）

- `tests/test_esp_runtime.py`：mock 子进程（idf.py / esptool），钉命令拼装、退出码解析、超时、panic 标记
- verify.py 派发测试：builder=idf / flash.backend=esptool / capture.backend=uart 三分支被正确路由；缺省配置路径行为逐字节不变（回归钉）
- 现有全量测试（860+）必须保持全绿——零破坏证明

### 5.2 真机终验（发布门槛，对齐"验收=真机全链路"铁律）

1. esp32s3-hello 内 `verify.py` 完整跑通，status ok，连续 ≥2 次
2. 负路径各验一次：拔线/占用 COM3 → 清晰报错非裸 traceback；改错 expect → verify 段 FAIL 且 build/flash 段仍 ok
3. 回归：stm32f103-adc-oled `verify.py --no-build` 照常 PASS（证明 STM32 路径零破坏）

## 6. 收尾清单

- 卸载 spike 临时 pip esptool
- toolkit：分支上 commit（不 push 不并 master，待用户验收裁决）；VERSION/CHANGELOG 不动（未发布态）
- memory：esp32-onboarding-deferred 转"已唤起落地"，multi-mcu-tooling-roadmap 更新 esptool v5 实况
- 顶层 README + 本工程 spec 入档

## 7. 风险登记

| 风险 | 缓解 |
|---|---|
| IDF 安装体量大（~4GB）且网络不稳 | 镜像源优先；分组件安装可断点重试 |
| IDF 子进程环境复杂（export 脚本注入） | esp_runtime 单点封装 + host 单测钉命令拼装，真机只验一次通路 |
| COM3 被监视串口占用（serial_monitor 在跑） | hw_lease 统一互斥；capture 前提示释放 |
| 烧录后复位时序（USB-CDC 重枚举丢开头日志） | capture 延时启动 1~2s + 周期 printf 兜底（固件本身周期输出） |
