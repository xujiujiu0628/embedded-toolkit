# embedded-toolkit

[![CI](https://github.com/xujiujiu0628/embedded-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/xujiujiu0628/embedded-toolkit/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/xujiujiu0628/embedded-toolkit?label=release&color=brightgreen)](https://github.com/xujiujiu0628/embedded-toolkit/releases/latest)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)

**AI 写嵌入式固件的闭环验证工作台：代码可以由 AI 生成，但"算不算对"由机器说了算。**

面向 **STM32F103 / ESP32-S3** 两族 MCU（架构可扩展），把 `需求契约 → 构建 → 烧录 →
真机输出采集 → 期望判定 → 发布门禁 → 反馈落账` 串成一条全自动判定链——AI 生成的
固件必须在自己板子上打印出符合契约的证据，才有资格打 tag。它解决的核心问题是：
**LLM 写固件无法自证正确**，而人眼盯串口又慢又漏。

版本线 v0.2 → v0.8（每个 tag 均过 G0~G3 真机门禁 + CI 全绿），逐版变更见
[Releases](https://github.com/xujiujiu0628/embedded-toolkit/releases) 与
[CHANGELOG](CHANGELOG.md)。正文中的 `F-xxx` / `GAP-x` 为内部账编号，每条在
CHANGELOG 有对应条目与证据 commit——**状态类事实以 CHANGELOG 为唯一权威**，
本 README 只写结构与非易失的实录，处置史不在此复制。

## Highlights

- **四态期望判定**——PASS / XFAIL（登记在案的"预期失败"欠条，须附理由）/
  XPASS（欠条已落地却未销账的意外通过，强制判红）/ FAIL，见[「怎么工作」](#怎么工作)
- **证据分级四档**——每次判定携带 `evidence` 字段，与 verdict 正交；
  仿真与静态证据进不了发布记录
- **G0→G3 发布门禁 + R1~R8 事后审计**——hex 字节哈希锚定"烧的是什么"、
  契约哈希锚定"拿什么判的绿"，"当时绿了"任何人**事后可重算**
- **无板闭环**——仓内自带 `examples/sim-demo`，QEMU 上同一判定引擎端到端跑绿
- **两族真机后端**——STM32（OpenOCD 烧录 + RTT/semihosting 采集）与
  ESP32-S3（idf 构建 + esptool 烧录 + UART 定时窗采集）均有真机全链实证
- **两族后端行为隔离**（F-174）——多平台后端矩阵**缺省配置行为逐字节不变**；
  OpenOCD 专属动作（判定后复位 / HardFault 层 2 诊断）按后端设闸互不越界
- **门禁失败即回滚**——G0→G3 四道检查（工作树干净 → 探针连通预检 →
  clean rebuild 重跑判定 + xfail 翻转确认 → 落记录打 annotated tag），
  **任一环失败自动回滚**
- **MCP 正门**——六个核心工具有界包装：子进程透传、入参白名单、
  **不给 agent 任意 shell**
- **纯 mock 回归套件**——不碰硬件、零第三方依赖（仅串口族需 pyserial），
  Windows/Linux 双腿全绿由 CI 每 push 实证
- **55 外设寄存器知识库** + 寄存器级外设代码生成——AI 生成物先过门控再进编译

## 一分钟试跑（零配置、零依赖、零硬件）

```bash
git clone https://github.com/xujiujiu0628/embedded-toolkit.git
cd embedded-toolkit
python -m unittest discover -s tests
```

回归套件是**纯 mock** 的（不碰硬件；仅串口工具族可选依赖 pyserial），
machine.json 缺失时自动回退 `machine.example.json` 模板并给出明确提示——
这条命令本身就是"陌生人克隆"路径的机检金丝雀（CI 每次必跑）。末行 `OK`
即通过；例数与 skipped 数随环境变化，以实跑输出为准（仓库纪律：文档不写死
数字）——缺 bash/arm-gcc/coverage/esp 工具链时 skip 增多，样例工厂动态生成
例在工具链不在场时整类不出现（是"缺席"不是 skip，见
tests/test_sample_factory.py 模块注记）。

> **Windows PowerShell 首跑的乱码告警**：你可能看到十几行
> `Warning: session_fix_cache.json , ԭļ: ...` 式乱码。这是反馈库把损坏缓存
> 主动隔离重建（F-020 诚实化设计，绝不裸 traceback）时写往 stderr 的中文
> 警告被 GBK 控制台解码所致——**终端显示问题，不是工具失败**，唯一判据是
> 末行 `OK` / `FAILED`。消除乱码：`$env:PYTHONIOENCODING = "utf-8"`。
> 另：hooks 行为测试在 Windows 请用 Git Bash 跑（PowerShell 全局 autocrlf
> 会造成行尾漂移假红，见 CONTRIBUTING）。

## 先无硬件尝鲜（一块板都不需要）

装好 **arm-none-eabi-gcc** 与 **QEMU**（`qemu-system-arm` 在 PATH，或
`machine.json` 填 `qemu_exe`）后：

```bash
python scripts/verify.py --project examples/sim-demo --json
```

仓内自带示例固件工程 `examples/sim-demo`：QEMU 直接加载 ELF 跑固件，
semihosting 收 printf 输出——**和真机路径完全相同的契约、判定引擎与 JSON 输出**。
仿真证据恒 `evidence="simulation_validated"`，与真机证据平级可信、但不进发布
门禁（G2 只认 `hardware_validated`）。跑通它，就理解了本项目的一半。

## 怎么工作

```text
需求(FSD/expectations.json) → 生成(Claude + review-code 对抗审查) → 构建(gcc_build / idf, F-174)
  → 真机判定(RTT / semihosting / UART 采集 printf) → 门禁(release.py G0-G3, 全绿才打 tag) → 落账(feedback_db.py 校准)
```

四个设计支点：

1. **判定外置**——"对不对"不写在 AI 的自觉里，写在版本化的契约文件里；AI 改代码
   可以，改契约会在发布审计的契约哈希锚（R1~R8 八查中的 R7）里现形。
2. **证据优先**——每条期望必须对应真机打印的字节（正则匹配 + 数值区间），
   `HAL_OK ≠ 字节正确` 是本仓库用一个月黑屏 OLED 换来的教训。
3. **异构审查**——工作台的维护者（AI）也会被换无上下文、不同模型家族的
   外部智能体审计，`handoff_guard` 机器强制其不碰硬件与禁区。
4. **失败现场诚实化**——超时/卡死/部分输出全部如实落盘
   （`last_failure.json`），绝不伪装成「程序无输出」。

### 判定四态与证据四档

期望契约（`expectations.json`）逐条判为：

| 状态 | 语义 |
|---|---|
| `PASS` | 信号在采集全文中按契约命中 |
| `XFAIL` | 登记在案的"预期失败"欠条（`"xfail": true` 必须携带 `xfail_reason`） |
| `XPASS` | 欠条已落地却未销账的**意外通过——强制判红**，杜绝"顺便实现了"静默混入 |
| `FAIL` | 正向匹配未命中，或负断言命中 |

仅构建/lint 的绿不算"验证过"，`static` 与真机证据分家——每条判定携带顶层
`evidence` 字段（与 verdict 正交：FAIL 也是真机证据，PASS 也可能是静态证据）：

| 取值 | 含义 |
|---|---|
| `"hardware_validated"` | capture 后端（rtt/semihosting）真机实跑采到运行时输出 |
| `"simulation_validated"` | sim 后端：qemu 直接加载 elf（`capture.backend: "sim"`，见 `examples/sim-demo`）——与真机平级的判定后端，**不进发布门禁**（G2 只认 hardware_validated） |
| `"static"` | 仅构建/lint，或 capture 未跑成——无任何运行时证据 |
| `"production_approved"` | 发布后经 `release_audit --approve` 人工批准投产（仅 audit 回填，verify 不产出） |

发布门禁（release.py G2）要求 `evidence == "hardware_validated"`，仿真/静态
证据混入发布需 `--allow-non-hardware-evidence` 显式豁免并留痕；事后审计
（release_audit.py R8）复核发布记录该字段，`production_approved` 缺批准
留痕视同篡改。发布记录同时自带 fidelity 契约字段（`fidelity_boundaries`
按证据等级声明"证明了什么/没证明什么"、`limitations` 缺省不虚报、
`signature` 留空占位）。

## 效果预览（真实可回放的实录）

以下输出为**历史实录工件**：版本号/哈希/数值按实录保留，不随版本推进改写
（本仓纪律 F-034：要反映新版本须真实重跑后整段替换）。

真机（STM32F103C8T6 + ST-Link，ADC 电位器 + OLED 工程）一次 `verify` 的 RTT
采集实录节选（0.2 时期）：

```text
=== adc-oled boot ===
[init] CLK OK
[init] ADC OK
[init] OLED OK
ADC raw=3961 mv=3192 (3.19 V)
ALERT HIGH mv=3192
ADC raw=3959 mv=3190 (3.19 V)
ALERT HIGH mv=3190
```

ESP32-S3（F-174 试点，idf build + esptool flash + UART 采集，
`capture.backend: "uart"`）同一契约引擎下的 expect 靶命中：

```text
ESP-PILOT-BOOT ok
ESP-PILOT-OK tick=1
```

对应的机器判定输出（`verify.py --json` 节选，全文真实可回放）：

```jsonc
{
  "toolkit_version": "0.2",
  "contract_hashes": {                      // 判绿锚点：结果由哪份契约产生
    "config_sha256": "e2711d16…f9fbb4",
    "expectations_sha256": "034d306e…7aa99b"
  },
  "steps": {
    "build":   { "status": "ok", "summary": "0 errors, 0 warnings (build)" },
    "flash":   { "status": "ok", "message": "** Verified OK **" },
    "capture": { "status": "ok", "method": "rtt", "lines": 34 },
    "verify":  { "status": "ok",
                 "matched": ["FR-SYS-01", "FR-ADC-01", "FR-ADC-02", "FR-ALERT-01"],
                 "missing": [] }
  },
  "status": "ok",
  "feedback": { "logged": true }            // 结果自动落账，供校准统计
}
```

> 本段为 **0.2 时期**的真机实录，`toolkit_version` 字段如实保留当时的 `"0.2"`。
> 0.5 起输出顶层新增 `evidence` 字段（含义见「判定四态与证据四档」）——上例若
> 在当前版本重跑，会多出 `"evidence": "hardware_validated"`；历史实录不加字段，
> 不回放篡改。

## 上手

### 环境要求

| 依赖 | 用途 | 备注 |
|---|---|---|
| Python **3.10+** | 全部脚本 | 标准库为主，串口族需 `pip install -r requirements.txt` |
| arm-none-eabi-gcc | 构建 | GNU Arm Embedded Toolchain（或 xPack） |
| GNU make | 构建 | Windows 推荐 MSYS2 的 make.exe |
| OpenOCD | STM32 烧录/RTT/semihosting 采集 | 推荐 xPack 发行版 |
| QEMU（可选） | 无板仿真判定后端（F-150） | `machine.json` 键 `qemu_exe` 或 PATH |
| ESP-IDF v5.4.x（含 esptool） | ESP32 后端构建/烧录/复位（F-174） | `machine.json` 键 `esp_idf_path` / `esp_tools_dir`；UART 采集另需 pyserial |
| ST-Link + STM32F103 板 | 仅 STM32 真机步骤 | 无板也能跑测试、lint、审计、代码生成、sim 闭环 |
| ESP32-S3 板（USB 串口） | 仅 ESP 真机步骤 | port/chip 走白名单校验（`COMn` 或 `/dev/tty*` 形态） |

平台现状：**Windows 为主要开发/真机平台**；工具链预检自 F-164 起统一
`shutil.which` 平台判定。Linux 上测试套、离线工具与无板仿真链（sim-demo
端到端）全量可跑（CI 即证）；Linux **真机烧录**路径未验证（见「已知限制」F-031）。

### 真机路径一次性配置

`machine.json` 是本机文件（不入库），是全部工具链绝对路径的**唯一合法源**：

```bash
cp machine.example.json machine.json
# 填 gcc_path / make_exe / openocd_exe；
# ESP32 后端另填 esp_idf_path / esp_tools_dir；QEMU 可选填 qemu_exe
```

### STM32 工程：5 分钟到第一次绿

前提：一个 CubeMX 生成、带顶层 `Makefile`（`TARGET=`/`BUILD_DIR=` 约定）的
STM32 工程。以下 `<工程根>` 指你的固件目录，脚本从任意 cwd 用 `--project` 指定。

```bash
# 1. 给工程建立工作台契约（【无需硬件】）——最小子集：
#    <工程根>/.workbench/config.json
{
  "toolkit_min_version": "0.1",
  "builder": "gcc",
  "gcc": { "project": "Makefile", "target": "main", "log_dir": ".workbench/build" },
  "capture": { "backend": "rtt", "port": 19021,
               "sram_base": "0x20000000", "sram_size": 2048,
               "id": "SEGGER RTT", "boot_delay_ms": 300 }
}
# 可选: "post_reset": false 加进 capture 段可关闭"判定后自动复位"
#（默认开——flash 实际发生过的运行在判定结束后执行 init;reset run;shutdown,
#  板子状态不留给下一次运行; 复位失败只落 post_reset 字段, 不改判定）

# 2. 写下期望清单（【无需硬件】）：
#    <工程根>/.workbench/expectations.json
{ "version": "1.0", "expectations": [
  { "id": "FR-SYS-01",  "desc": "启动完成横幅",   "texts": ["=== boot ===", "[init] CLK OK"] },
  { "id": "FR-ADC-02",  "desc": "ADC 毫伏输出",   "patterns": ["mv=(\\d{4})"],
                                                    "capture_group": 1, "min": 3000, "max": 3400 },
  { "id": "FR-FUTURE-1","desc": "已知未做，挂起", "texts": ["TODO"],
    "xfail": true, "xfail_reason": "功能未实现，登记在案" }
]}

# 3. 提交前静态校验契约（【无需硬件】，秒级）
python scripts/expectations_lint.py --project <工程根>

# 4. 构建 + 烧录 + 采集 + 判定（【需板子】；--json 供 AI 消费）
python scripts/verify.py --project <工程根> --json

# 4b. 没板子？见上文「先无硬件尝鲜」——examples/sim-demo 用同一命令与引擎

# 5. 发布演练（【需板子】，dry-run 不打 tag 不落库）
python scripts/release.py --project <工程根> --tag v1.0.0 --dry-run
```

（上述第 1、2 步示例即本仓契约 fixture 的公示值——`tests/test_contract_fixtures.py`
双处对账，示例与 loader 行为漂移会当场打红。）

### ESP32-S3 工程（F-174）

前提：ESP-IDF v5.4.x 已 `install.ps1 esp32s3`，`machine.json` 填好
`esp_idf_path` / `esp_tools_dir`；工程为标准 IDF 工程（`idf.py build` 可跑通）。
`.workbench/config.json` 换三件后端即可，期望契约与判定引擎完全复用：

```jsonc
{
  "toolkit_min_version": "0.6",
  "builder": "idf",                                  // 构建经 esp_runtime → idf.py
  "idf":  { "build_timeout": 900 },
  "flash":  { "backend": "esptool", "port": "COM3" },// 烧录走 idf.py flash (flash_args 单一事实源)
  "capture":{ "backend": "uart", "port": "COM3",     // esptool --after hard_reset 确定性复位
              "baudrate": 115200, "duration_sec": 15,// → pyserial 定时窗采集
              "chip": "esp32s3" },                   // 可省 (默认 esp32s3); port/chip 均过白名单校验
  "verify": { "expect": ["ESP-PILOT-BOOT ok"] }
}
```

要点：

- 三键（`builder` / `flash.backend` / `capture.backend`）任一缺失或取值非法且
  ESP 标记在场时，verify 在任何构建/烧录动作之前 **fail-fast 拒绝**（GAP-F-19
  收口，规则本体 `runtime_common.esp_backend_config_errors`）
- ESP 模式下 OpenOCD 专属动作自动让位：`post_reset` 记 `skipped`、HardFault
  层 2 双路抑制——ESP panic 的归因走采集文本中的 `esp_panic` 标记 + AI 判定
  （panic 帧随链接线离线 addr2line 符号化已落地，F-200）
- uart 采集开口即释放 DTR/RTS（F-177：CH340/CP210x 自动下载电路否则会把芯片
  按在复位里收 0 行；释放附带一次确定复位）；非 S3 芯片族必须显式设
  `capture.chip`，探针判错芯片型会在复位步体面报错
- **STM32 工程也能用 uart 采集（F-231）**：`capture.reset` 三选一——
  `esptool`（缺省，ESP32 路径）、`openocd`（ST-Link 复位，复用
  `openocd_runtime.reset_target`）、`none`（调用方已自行复位）。非 esptool
  模式跳过 `capture.chip` 白名单，且 `capture.backend="uart"` 不再被当成 ESP
  标记（不触发 GAP-F-19 混配拦截）；例：
  `"capture": {"backend": "uart", "port": "COM4", "reset": "openocd",
  "baudrate": 115200, "duration_sec": 20}`。

### 采集窗纪律（真人输入类期望，如按键/旋钮）

1. **窗口在烧录之后才开**——全链 `verify.py --json` 前置 build+flash 约 1 分钟，
   提前按=白按。交互前先跑 `--no-build --no-flash`（板已是目标固件），窗口几秒内开。
2. **采集窗由你自持**：`python <toolkit>/scripts/verify.py --project <工程根> --no-build --no-flash --timeout 40`，
   盯着屏/串口自己把握动作节奏；AI 代发"现在开始按"的回合制协调已多次证伪。
3. **连拍优于单点**：窗内动作做 5-6 次（消抖节流会吃掉部分，如 button-toggle 60s 实测 TGL 152 行）。
4. **判 fail ≠ 工具坏**：`evidence=hardware_validated` 说明采集链正常，`missing` 项优先怀疑
   动作未落在窗内/未达契约阈值（旋钮类）——先看 `captured_output` 再决定重跑。
5. **SWD 连不上先过物理面**：先确认探针/板线在场且你当下的按键动作状态，再查软件面。

## 工具速查

### 离线工具（无硬件即可跑）

| 工具 | 一句话 | 典型命令 |
|---|---|---|
| `scripts/gcc_build.py` | GCC/make 构建后端，JSON 契约输出 + 产物登记 | `python scripts/gcc_build.py --project <工程根>` |
| `scripts/expectations_lint.py` | expectations.json 提交前校验 E1~E11（含 F-112 负断言） | `python scripts/expectations_lint.py --project <工程根>` |
| `scripts/fsd_coverage.py` | FSD 需求 ↔ expectations 断言对账 C1/C2/C3 + 漂移对照表（F-113） | `python scripts/fsd_coverage.py --project <工程根>` |
| `scripts/release_audit.py` | 发布记录事后八查 R1~R8（tag 指向/hex 重算/契约锚/证据等级） | `python scripts/release_audit.py --project <工程根> --all` |
| `scripts/handoff_guard.py` | 外部智能体代管分支的三级禁线机检 | `python scripts/handoff_guard.py --branch <代管分支>` |
| `scripts/feedback_db.py` | 修复事件落账 + 每流水线准确率校准 | `python scripts/feedback_db.py --stats` |
| `scripts/rm_lookup.py` | STM32F103 55 外设寄存器/位域/引脚速查（JSON 知识库） | `python scripts/rm_lookup.py --list` |
| `scripts/gen_periph.py` | 参数 → 寄存器级 C 初始化代码 / 外设文档（时钟经 `--hclk`/`--pclk1`/`--pclk2` 参数化，定时器内核时钟按 RM0008 §7.3.7 派生；SPI 帮手逐字节排空 RX，F-178；细则 `--help`） | `python scripts/gen_periph.py --help` |
| `scripts/capture_sim.py` | sim 采集会话：qemu-system-arm 直接加载 elf（无板闭环，F-150） | 经 `verify.py` 消费（见「先无硬件尝鲜」） |
| `scripts/mcp_server.py` | MCP 接入：六工具有界包装（见「MCP 接入」），零业务复制 | 见「MCP 接入」节 |

### 真机工具（需板子/探针）

| 工具 | 一句话 | 典型命令 |
|---|---|---|
| `scripts/verify.py` | 闭环编排：build→analyze→flash→capture→判定，`--json` 结构化输出（配置 sim 后端时无硬件） | `python scripts/verify.py --project <工程根> --json` |
| `scripts/release.py` | G0→G3 门禁发布：全绿才打 tag，记录含双重哈希锚 | `python scripts/release.py --project <工程根> --tag vX.Y.Z --dry-run` |
| `scripts/hardfault.py` | HardFault 现场：寄存器 + 符号表定位出错函数 | `python scripts/hardfault.py --json` |
| `scripts/esp_runtime.py` | ESP32 三后端封装：idf.py build / esptool flash / UART 定时窗采集 + esp_panic 文本标记（F-174） | 经 `verify.py` 派发（`builder=idf`） |
| `scripts/serial_*` / `openocd_*` | 串口与探针底层族（RTT/GDB/telnet） | `python scripts/<name>.py --help` |

## 工程契约（`.workbench/`）

固件工程通过 `.workbench/config.json` 被发现（从 cwd 逐级向上查找，兜底识别
旧版 `.embeddedskills/config.json`）。期望判定规则：

- `id` 唯一必填；`texts`（全 substring 命中）与 `patterns`（全正则 search 命中）二选一
- `"xfail": true` 必须携带 `xfail_reason`——待办欠债全部白纸黑字
- 数值断言：`patterns` + `capture_group` + `min`/`max` 区间
- **负断言（F-112）**：`forbidden_texts` / `forbidden_patterns`——捕获全文任一命中
  即该条 FAIL（优先于正向匹配与 XPASS），对应 FSD `prohibited_outcomes` 的可机检项
- **豁免登记（F-113）**：顶层 `"waived"` 数组登记不走 verify 闭环的需求（理由必填）；
  `fsd_coverage.py` 对账 FSD↔断言，xfail（欠条）与 waived（豁免）两级不混用
- 版本控制建议：`config.json` / `expectations.json` / `releases/` 入库；
  `build/` 与 `state.json`（可再生缓存）忽略

**设备锁（F-145）**：`verify` 的 flash+capture 段与 `openocd_run flash/erase`
全程持有**机器级设备锁**（`%USERPROFILE%\.embedded-toolkit\device-locks\stlink.lock`，
OS 级文件锁）——同一探针/板子同时只被一个 agent（或同一台机的另一份 clone）
占用，ESP 运行同样经这把锁排队（宁多排不错排）；进程崩溃 = OS 自动放锁。
冲突方收到 `resource_busy` + 持有者 purpose/获取时间，`--lease-wait N` 可有界
等待。它与 `.workbench/state.json` 的写锁（F-127，防数据竞争）是两层，互不替代。

## MCP 接入（AI agent 第一接口）

把六个核心工具包装成有界 MCP 工具（stdio transport）：`run_verify` /
`lint_expectations` / `gen_peripheral` / `rm_lookup` / `diagnose_hardfault`
（仅解析不触探针）/ `doctor`。安全设计：工具=对现有脚本的子进程透传（零业务
逻辑复制，CLI 仍是唯一事实源）、入参白名单校验、**不给 agent 任意 shell**。

```bash
# MCP SDK 是唯一可选依赖（其余工具零第三方依赖，不受影响）
pip install -r requirements-mcp.txt
```

Claude Code 注册：把仓根 `.mcp.json.example` 拷为工程根（或 `~/.claude`）的
`.mcp.json`（本机文件，不入库），把 `<TOOLKIT_ROOT>` 替换为本仓绝对路径：

```jsonc
{
  "mcpServers": {
    "embedded-toolkit": {
      "command": "python",
      "args": ["<TOOLKIT_ROOT>/scripts/mcp_server.py"]
    }
  }
}
```

`run_verify` 等需要工程的工具要求 `project` 参数指向持有
`.workbench/config.json` 的固件工程根——不存在或不是工程即拒绝。

## 安全

**安全漏洞请按 [SECURITY.md](SECURITY.md) 私下报告，勿开公开 issue。**

### ⚠️ 信任边界：勿对不受信的工程跑 verify / MCP `run_verify`（F-219, L-3）

本工具**按"配置即意图"执行**：`.workbench/config.json` 不只是数据，它能
**决定在你的机器上执行什么**——

| 键 | 决定 |
|---|---|
| `gcc.project` | 构建时 `make -f <该值>` 跑哪个 Makefile（`gcc_build.py:188`） |
| `gcc.target` | 传给该 Makefile 的 target |
| `capture.sim.exe` | sim 后端启动哪个可执行文件（`capture_sim.py:48`） |
| `flash.backend` / `capture.backend` / `builder` | 换整条后端（OpenOCD / esptool / uart / idf） |

**故：把 `verify.py` / MCP `run_verify` 指向一个你不知道来源的工程，等同于
以你的权限执行那个工程作者指定的任意命令**（Makefile 可含任意 shell
recipe；`sim.exe` 直接是任意二进制）。设备锁、bounded argv、参数白名单
都**不覆盖这一条**——它们防的是参数注入与并发抢占，不是"该不该信这个工程"。

**规避**：只对自己写过、或来源可审计的工程跑 verify；`project` 指向他人
仓库前先读其 `.workbench/config.json` 的 `gcc.project` 与 `capture.sim.exe`。
CI 与只读工具（`rm_lookup` / `fsd_coverage` / `expectations_lint` 等纯离线
命令）不受此限——它们不读 config 决定执行面。

> 登记口径：这是**设计边界不是缺陷**——工具链的职责是把声明的构建跑起来，
> 不是替调用者判断声明可不可信。变更此项须同步更新本节与 `CHANGELOG` F-219
> （本节由 `tests/test_readme_trust_boundary.py` 存在性钉守护）。

## 质量与 CI

- 回归套件：`python -m unittest discover -s tests` 全绿为准（例数随修复增长，
  以实跑为准）
- CI 每 push 必跑（job 清单以 `.github/workflows/ci.yml` 为准）：unittest
  四腿矩阵（ubuntu×windows × Python 3.10/3.12）、coverage-gate（棘轮下限，
  只升不降）、lint（ruff E/F）、coverage-lint（零覆盖清单 --strict）、
  syntax-smoke（ubuntu 真实 arm-gcc 编译生成物）、sim-demo（ubuntu qemu
  无板端到端闭环 + test-report check run）；真机冒烟另有 `hw-smoke.yml`
  门控形态（self-hosted runner 就绪才跑）
- 发布记录可信度：`release_audit` 对既有真实记录跑 CLEAN/预期 WARNED，
  篡改场景（换清单/搬记录）由测试固化
- 贡献纪律（修 bug 必带回归测试、先红后绿、契约变更三件套、分层 import 契约）
  以 [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) 为权威，本节不重复

## 已知限制

本区只登记**今天仍存在**的限制，每条的影响/规避/处置史一律以
[CHANGELOG](CHANGELOG.md) 为准（已闭合项不留本区）：

- **Linux 真机烧录/采集未验证**（F-031，部分闭合）——Linux 上测试套、离线工具
  与 sim-demo 无板闭环全量可跑（CI 每 push 实证），真机烧录仅 Windows 验证过；
  欲补 Linux 真机验证欢迎开 issue。
- **serial_mux 仅 Linux/macOS**（F-032，socat 依赖）——直连物理串口即可满足
  verify 全链，RTT/semihosting/UART 采集后端均不经 mux 层。
- **v0.5 发布记录 R7 永久 FAILED**（F-169，登记语义）——历史 autocrlf 切换致
  工作树/入库字节永久错位（构造性证据坐实，非篡改）；`release_audit --tag v0.5`
  预期 FAILED，勿当新伤，其余发布记录不受影响。
- **共享向量 TIM 的 ISR 向量名非 CMSIS 实名**（GAP-F-20，暂缓）——
  TIM9/12/13/14 等共享向量外设按生成物定义的 `TIM9_IRQHandler` 不会接进向量表
  （编译链接全绿、ISR 永不执行）；危害面以"非 C8 目标 + 手工取用生成物"为界
  （TIM8~14 均 `available_on_c8=False`）。唤起条件=样例工厂二期/非 C8 立项。
- **引脚映射数据仅 LQFP48/xB 切片**（GAP-F-21）——`data/pin-mapping-f103.json`
  当前锁 LQFP48 单封装，64/100/144 脚多封装维度与 arch-facts 格式统一暂缓；
  TIM5/ADC3/TIM8/SDIO/FSMC/DMA2 引脚映射在官方 LQFP48 表零行，宁缺毋滥不硬造
  （F-193 查证）；架构常量（IWDG 魔数/PLLMUL 编码等）改由
  `data/stm32f103-arch-facts.json` 带出处入册（F-179），消费方以 RCC 位名与该
  档为准。
- **锁面收口待办**（F-230 登记，三号复审 N-7/N-8/N-9）——`file_lock` 为无限
  阻塞，与 `state_write_lock` 的"超时降级"策略相反（持锁方挂起会拖停所有
  构建/写回）；`releases/<tag>.json` 有两个写入方（`release.py` 与
  `release_audit.py --approve`）且无共用锁；CAS 归还依赖 `os.link` 硬链，
  FAT/exFAT/部分 SMB 上失败且当前静默。三处同族，宜一张票统一收口。
- **`rm_lookup.py --pins ""` 用法错误返回 rc=0**（F-230 登记，三号复审
  N-10）——与 `release_audit` 已钉住的"用法/环境错误 → 2"口径不一致；属
  批外既有行为，空串语义（未给参数 / 非法参数）待裁决。
- **feedback_db 为单会话假设**（WB-05 N-1）——多进程读改写无锁，跨进程并发写
  可能互相覆盖台账。
- **UART 串口补丁的发布门禁脆弱性**——有意搁置（成本/收益不立项，裁决记录见
  CHANGELOG）。
- **贡献者两坑**：PEP 701 f-string 写法在 py3.10 CI 腿上整腿炸（3.12 才放宽；
  `tests/test_py_floor.py` tokenize 扫描钉守卫，F-181）；Windows 上 hooks 行为
  测试的 bash 解析可能命中 `System32\bash.exe`（WSL 启动器假命中）——解析器
  逐候选探测跳过 system32，全部不可用则带诊断 skip 不静默假红（同 F-181）。

## 路线图（只登记未闭合项）

已落地方向（MCP 正门、无板仿真闭环、ESP32 最小闭环与 panic 符号化、真机 CI
冒烟门控、OpenOCD cfg 参数化）各以对应账收敛于 CHANGELOG，此不复述。在途：

- **演示录屏**——一次 verify 从烧录到判 PASS 的全过程（asciinema/板载实录），
  backlog；现 README 以「效果预览」的逐字实录为证据，不用摆拍素材
- **分发形态**（PyPI / uvx / Claude Code 插件"一行安装"）——暂缓，唤起条件 =
  决定对外推广 toolkit 的那天，届时先做 spike 再立项
- **ESP 后续**——WiFi/BLE、probe-rs 调试、xiaozhi 类业务工程接入，按立项裁决后置
- **多探针细粒度设备锁**——现锁为机器级（F-145），更细列为后续
- **pin-mapping 多封装维度**——唤起条件 = 新封装/新芯片立项（GAP-F-21）

## 生态位

同类项目各有所长：agentic-hil 以有界 MCP 工具 + 硬件租约 + plan 门禁见长，
agentic-embedded-lab 做仿真控制面（claim + fidelity 证据分级），pytest-embedded /
Renode 把仿真做成平级判定后端，hardci / jlink-mcp 验证了 MCP 分发路径。

本仓的独特处不在单点能力，而在**完整治理链**——同类项目普遍假设"固件已存在
只管测"，本仓从需求一路管到事后审计：四态判定（XPASS 判红）→ FSD↔断言双向
对账（`fsd_coverage.py`，欠条与豁免两级不混用）→ G0–G3 发布门禁 + R1–R8
事后审计（证据四档，发布后篡改在契约哈希锚与批准留痕下现形）→ 反馈校准
（`feedback_db.py` 按流水线长出准确率）→ 寄存器知识库 + 代码生成（AI 生成物
先过门控再进编译）。

## 项目结构

```text
embedded-toolkit/
├── scripts/            # 40+ 个 .py（入口 verify.py；共享层 wb_common + runtime_common
│                       #   单一事实源 + wb/openocd/serial 三 runtime，F-029；
│                       #   legacy/ 空目录占位，Keil 退役区已拆 archive，F-067b）
├── tests/              # unittest 回归套件（纯 mock，Win/Linux 全绿）
├── data/               # 知识库：55 外设参考 JSON + 架构常量档（arch-facts，F-179）+ 已知限制
├── config/             # 串口/探针族的环境级配置
├── hooks/              # 固件工程侧三条 C 铁律（禁 malloc / 禁逻辑层 HAL_Delay / volatile 告警）
├── templates/          # FSD 需求规格书模板 + RTT 版 HardFault 现场 handler
├── machine.json        # 本机工具链路径（不入库；模板 machine.example.json）
├── CHANGELOG.md        # 全账本：条目可对到 commit（状态类事实唯一权威）
└── VERSION             # 当前 0.8（版本唯一事实源 = VERSION 文件，经 wb_common.toolkit_version() 读取）
```

## 文档索引

- [`CHANGELOG.md`](CHANGELOG.md) — 版本账本（每条对到证据 commit）
- [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) — 环境准备 / 测试与 PR
  纪律 / 分层契约 / 禁区 / 例外条款
- [`templates/fsd-template-stm32.md`](templates/fsd-template-stm32.md) — 需求规格书模板
- [`templates/hardfault_rtt.c`](templates/hardfault_rtt.c) — RTT 工程 C 级
  HardFault 现场 handler（F-115）：新工程接入 = 复制到 User/ + Makefile
  C_SOURCES 加一行 + 删除工程自有 `HardFault_Handler` 死循环桩让位强符号
- Keil 退役区唤起（archive 物理副本）：`<d-claude-root>\archive\
  embedded-toolkit-keil-legacy-20260905\README.md`——2026-09-05 F-067b 起
  Keil 退役桥（keil_build / keil_analyze / keil_project + 错误码库等）已从
  仓内拆出；按需唤起见该 README（也可走 `EMBEDDED_TOOLKIT_KEIL_ARCHIVE`
  环境变量指 archive 路径）
- 维护者 ↔ Agent 协作私约（handoff 对账链、fresh-checker 模板等）自 0.4 边界
  决策迁维护者私有仓，公开工具库不含；公开面机制本体见 `handoff_guard` 与
  CHANGELOG 治理账

## 贡献

- **Bug / 功能请求**：用 [Issue 模板](.github/ISSUE_TEMPLATE/) 提报（附工具链
  版本与 OS/Python 信息；verify 相关请附 `verify.py --json` 完整输出，失败现场
  另有 `.workbench/build/last_failure.json` 可一并贴上）
- **PR**：按 [PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) 填写；
  提交前 `python -m unittest discover -s tests` 全绿并把统计行贴进 PR；
  修 bug 必带回归测试（详见 CONTRIBUTING）
- **安全问题**：按 [SECURITY.md](SECURITY.md) 私下报告
- 社区行为准则见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## License

[MIT](LICENSE)

## 附：代号与命名沿革

*代号 **arbiter**（裁判机）— 名字沿革注记（F-173）：仓名 `embedded-toolkit` 停在
0.1~0.4 的纯工具期；0.5 之后内核已长成判定链（门禁拒绝、证据分级、哈希锚是裁判
属性不是工具属性）。仓名不改——GitHub 地址、CI 徽章、各工程 `.workbench` 与
VS Code tasks 的绝对路径引用、以及 v0.2~v0.6 全部 tag 都钉在它身上，发布锚点
不可变是本仓自己的第一纪律。改的是这行字：你面前这个项目的本质是裁判，工具箱
只是它的手。*
