# embedded-toolkit

[![CI](https://github.com/xujiujiu0628/embedded-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/xujiujiu0628/embedded-toolkit/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)

**AI 写嵌入式固件的闭环验证工作台：代码可以由 AI 生成，但"算不算对"由机器说了算。**

面向 **STM32F103 / ESP32-S3** 两族 MCU（架构可扩展），把 `需求契约 → 构建 → 烧录 →
真机输出采集 → 期望判定 → 发布门禁 → 反馈落账` 串成一条全自动判定链——AI 生成的
固件必须在自己板子上打印出符合契约的证据，才有资格打 tag。它解决的核心问题是：
**LLM 写固件无法自证正确**，而人眼盯串口又慢又漏。

版本线 v0.2 → v0.6（每个 tag 均过 G0~G3 真机门禁 + CI 全绿），逐版变更见
[Releases](https://github.com/xujiujiu0628/embedded-toolkit/releases) 与
[CHANGELOG](CHANGELOG.md)（每条账可对到证据 commit）。

## 零配置试跑（任何人，1 分钟）

```bash
git clone https://github.com/xujiujiu0628/embedded-toolkit.git
cd embedded-toolkit
python -m unittest discover -s tests
```

无需任何配置与第三方依赖：回归套件是**纯 mock** 的（不碰硬件；仅串口工具族
可选依赖 pyserial），machine.json 缺失时自动回退 `machine.example.json` 模板
并给出明确提示——这条命令本身就是"陌生人克隆"路径的机检金丝雀（CI 每次必跑）。
例数以实跑输出为准（仓库纪律：文档不写死数字）。末行 `OK (skipped=1)` 即通过。

### Windows PowerShell 首次跑测试的乱码告警

PowerShell 下你可能看到十几行类似 `Warning: session_fix_cache.json , ԭļ: ...`
的乱码。**这是终端 GBK 编码显示问题，不是工具失败**——反馈库发现损坏缓存时会
主动隔离为 `.corrupt` 并重建（F-020 诚实化设计，绝不裸 traceback），其写往
stderr 的中文警告被 PowerShell 按 GBK 解码所致。判定方法：看最后一行
`OK (skipped=1)` / `FAILED`。想消除乱码：

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m unittest discover -s tests
```

另注意 hooks 行为测试在本机 Windows 上请用 Git Bash 跑（PowerShell 全局
autocrlf 会造成行尾漂移假红，见 CONTRIBUTING）。

## 无硬件快速体验（一块板都不需要）

装好 **arm-none-eabi-gcc** 与 **QEMU**（`qemu-system-arm` 在 PATH，或
`machine.json` 填 `qemu_exe`）后：

```bash
python scripts/verify.py --project examples/sim-demo --json
```

仓内自带示例固件工程 `examples/sim-demo`：QEMU 直接加载 ELF 跑固件，
semihosting 收 printf 输出——**和真机路径完全相同的契约、判定引擎与 JSON 输出**。
仿真证据恒 `evidence="simulation_validated"`，与真机证据平级可信、但不进发布
门禁（G2 只认 `hardware_validated`）。跑通它，就理解了本项目的一半。

## 特性

（下文 `F-xxx` 为内部账编号，每条在 [CHANGELOG](CHANGELOG.md) 有对应条目。）

### 判定与证据

> 为什么需要：LLM 生成的固件"看起来对"不等于"跑起来对"，判定必须外置成
> 机器可评估的契约，而不是模型的自觉。

- **四态期望判定**：`expectations.json` 契约驱动，每条期望判为 PASS /
  XFAIL（登记在案的"预期失败"欠条，须附理由）/ XPASS（欠条已落地却未销账的
  意外通过——强制判红）/ FAIL
- **真机证据采集**：RTT / semihosting 双后端抓取固件 printf 输出，数值断言
  （正则 + capture_group + min/max）直接编进契约
- **多平台后端矩阵（F-174）**：STM32 = OpenOCD 烧录 + RTT/semihosting 采集；
  ESP32-S3 = `idf.py` 构建 + esptool 烧录 + UART 定时窗采集（真机双 PASS 收口）；
  QEMU sim 作无板平级判定后端（不进发布门禁）。**缺省配置行为逐字节不变**，
  OpenOCD 专属动作（判定后复位 / HardFault 层 2 诊断）按后端设闸互不越界
- **证据分级四档**：每次判定携带 `evidence` 字段
  （`hardware_validated` / `simulation_validated` / `static` /
  `production_approved`），与 verdict 正交——见「效果预览」段说明表

### 发布与审计

> 为什么需要："当时绿了"要能被任何人**事后重算**，绿的资格才可继承。

- **发布门禁 G0→G3**（四道检查：工作树干净 → 探针连通预检 → clean rebuild
  重跑判定 + xfail 翻转确认 → 落记录打 annotated tag），任一环失败自动回滚
- **双重取证锚**：hex 字节哈希锚定"烧的是什么"，契约哈希（sha256）锚定
  "拿什么判的绿"——发布记录可被 `release_audit` 的事后八查（R1~R8）逐条重算

### 治理与工程

> 为什么需要：这套系统服务于 AI 协作，所以 AI 本身也是被治理对象。

- **失败现场诚实化**：超时/卡死/部分输出全部如实落盘（`last_failure.json`），
  绝不伪装成"程序无输出"
- **AI 治理 AI**：`handoff_guard` 三级禁线机检外部智能体的代管分支
  （硬件禁触/文件禁区/主流程警告），两轮外部异构智能体独立审查已实战闭环
- **纯 mock 回归套件**：不碰硬件、零第三方依赖（仅串口工具需 pyserial）、
  Windows/Linux 全绿（CI 每跑即验证"陌生人克隆"路径）——例数以
  `python -m unittest discover -s tests` 实跑为准（CONTRIBUTING 约定文档不写死数字）
- **知识沉淀**：55 外设寄存器知识库 + 寄存器级外设代码生成 + 构建错误知识库
  自生长（五重门控防污染）

## 效果预览

真机（STM32F103C8T6 + ST-Link，ADC 电位器 + OLED 工程）一次 `verify` 的 RTT
采集实录节选：

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

ESP32-S3（F-174 试点，idf build + esptool flash + UART 采集）同一契约引擎下的
expect 靶命中（`capture.backend: "uart"`，esptool `--after hard_reset` 确定性
复位后开采集窗）：

```text
ESP-PILOT-BOOT ok
ESP-PILOT-OK tick=1
```

对应的机器判定输出（`verify.py --json` 节选，全文真实可回放）：

> 注：本段为 **0.2 时期**的真机实录，`toolkit_version` 字段如实保留当时的 `"0.2"`
> （不随版本推进改写历史输出）。0.3 的输出字段结构与此一致，仅版本号与哈希值不同。
>
> **0.5 起新增顶层 `evidence` 字段**（证据分级，输出契约的一部分；命名对齐
> agentic-embedded-lab 的 claim+fidelity 五级、裁剪 model_dependent 后四档，
> F-146 一次性切换不留别名）：本次判定的证据从哪来，与判定 verdict 正交——
> FAIL 也是真机证据，PASS 也可能是静态证据。
>
> | 取值 | 含义 |
> |---|---|
> | `"hardware_validated"` | capture 后端（rtt/semihosting）真机实跑采到运行时输出 |
> | `"simulation_validated"` | sim 后端：qemu 直接加载 elf（`capture.backend: "sim"`，见 `examples/sim-demo`）——与真机平级的判定后端，**不进发布门禁**（G2 只认 hardware_validated） |
> | `"static"` | 仅构建/lint，或 capture 未跑成——无任何运行时证据 |
> | `"production_approved"` | 发布后经 `release_audit --approve` 人工批准投产（仅 audit 回填，verify 不产出） |
>
> 发布门禁（release.py G2）要求 `evidence == "hardware_validated"`，仿真/静态
> 证据混入发布需 `--allow-non-hardware-evidence` 显式豁免并留痕；事后审计
> （release_audit.py R8）复核发布记录该字段，`production_approved` 缺批准
> 留痕视同篡改。发布记录同时自带 fidelity 契约字段（`fidelity_boundaries`
> 按证据等级声明"证明了什么/没证明什么"、`limitations` 缺省不虚报、
> `signature` 留空占位）。上例若在当前版本重跑，顶层会多出
> `"evidence": "hardware_validated"`——历史实录不加字段，不回放篡改。

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

## 它是怎么工作的

```text
需求(FSD/expectations.json) → 生成(Claude + review-code 对抗审查) → 构建(gcc_build / idf, F-174)
  → 真机判定(RTT / semihosting / UART 采集 printf) → 门禁(release.py G0-G3, 全绿才打 tag) → 落账(feedback_db.py 校准)
```

三个设计支点：

1. **判定外置**——"对不对"不写在 AI 的自觉里，写在版本化的契约文件里；AI 改代码
   可以，改契约会在发布审计的契约哈希锚（R1~R8 八查中的 R7）里现形。
2. **证据优先**——每条期望必须对应真机打印的字节（正则匹配 + 数值区间），
   `HAL_OK ≠ 字节正确` 是本仓库用一个月黑屏 OLED 换来的教训。
3. **异构审查**——工作台的维护者（AI）也会被换无上下文、不同模型家族的
   外部智能体审计，`handoff_guard` 机器强制其不碰硬件与禁区
   （历史对账记录在维护者私有仓 `<维护者私有仓>/docs/handoff/`，不在本仓）。

## 环境要求

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
`shutil.which` 平台判定（nt 按 PATHEXT 试 `.exe`，POSIX 查可执行位），
Linux 上测试套、离线工具与无板仿真链（sim-demo 端到端）全量可跑（CI 即证）；
Linux **真机烧录**路径未验证（F-031，见「已知限制」），欢迎报告。

## 真机路径配置（用板子之前做一次）

`machine.json` 是本机文件（不入库），是全部工具链绝对路径的**唯一合法源**：

```bash
cp machine.example.json machine.json
# 填 gcc_path / make_exe / openocd_exe；
# ESP32 后端另填 esp_idf_path / esp_tools_dir；QEMU 可选填 qemu_exe
```

（Windows 编码告警与跑测试相关，见上文「零配置试跑」小节尾注。）

## 5 分钟上手

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

# 4b. 没板子？见上文「无硬件快速体验」——examples/sim-demo 用同一命令与引擎

# 5. 发布演练（【需板子】，dry-run 不打 tag 不落库）
python scripts/release.py --project <工程根> --tag v1.0.0 --dry-run
```

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

ESP 模式下 OpenOCD 专属动作自动让位（F-174 终审修复波）：`post_reset` 记
`skipped`、HardFault 层 2 双路抑制——ESP panic 的归因走采集文本中的
`esp_panic` 标记 + AI 判定。采集窗起点纪律与 STM32 相同（烧录/复位后才开）。
uart 采集开口即释放 DTR/RTS（F-177：CH340/CP210x 自动下载电路否则会把芯片
按在复位里收 0 行；释放附带一次确定复位；S3 试点板为 FTDI 桥，回归双 PASS
实证无影响）。非 S3 芯片族
必须显式设 `capture.chip`——默认 `esp32s3`，探针判错芯片型会在复位步体面报错。

## 使用注意：采集窗纪律（真人输入类期望，如按键/旋钮）

1. **窗口在烧录之后才开**——全链 `verify.py --json` 前置 build+flash 约 1 分钟，
   提前按=白按。交互前先跑 `--no-build --no-flash`（板已是目标固件），窗口几秒内开。
2. **采集窗由你自持**：`python <toolkit>/scripts/verify.py --project <工程根> --no-build --no-flash --timeout 40`，
   盯着屏/串口自己把握动作节奏；AI 代发"现在开始按"的回合制协调已多次证伪。
3. **连拍优于单点**：窗内动作做 5-6 次（消抖节流会吃掉部分，如 button-toggle 60s 实测 TGL 152 行）。
4. **判 fail ≠ 工具坏**：`evidence=hardware_validated` 说明采集链正常，`missing` 项优先怀疑
   动作未落在窗内/未达契约阈值（旋钮类）——先看 `captured_output` 再决定重跑。
5. **SWD 连不上先过物理面**：先确认探针/板线在场且你当下的按键动作状态，再查软件面。

## 核心工具速查

### 离线工具（无硬件即可跑）

| 工具 | 一句话 | 典型命令 |
|---|---|---|
| `scripts/gcc_build.py` | GCC/make 构建后端，JSON 契约输出 + 产物登记 | `python scripts/gcc_build.py --project <工程根>` |
| `scripts/expectations_lint.py` | expectations.json 提交前校验 E1~E11（含 F-112 负断言） | `python scripts/expectations_lint.py --project <工程根>` |
| `scripts/fsd_coverage.py` | FSD 需求 ↔ expectations 断言对账 C1/C2/C3 + 漂移对照表（F-113） | `python scripts/fsd_coverage.py --project <工程根>` |
| `scripts/release_audit.py` | 发布记录事后八查 R1~R8（tag 指向/hex 重算/契约锚/证据等级） | `python scripts/release_audit.py --project <工程根> --all` |
| `scripts/handoff_guard.py` | 外部智能体代管分支的三级禁线机检 | `python scripts/handoff_guard.py --branch <代管分支>` |
| `scripts/feedback_db.py` | 修复事件落账 + 每流水线准确率校准 | `python scripts/feedback_db.py --stats` |
| `scripts/rm_lookup.py` | STM32F103 55 外设寄存器/位域速查（JSON 知识库） | `python scripts/rm_lookup.py --list` |
| `scripts/gen_periph.py` | 参数 → 寄存器级 C 初始化代码 / 外设文档（时钟经 `--hclk` 参数化，默认 72MHz 按标准 APB 分频推导，非默认值生成物头注回显前提；`--pclk1/--pclk2` 显式 APB 时钟覆盖逐键独立，定时器内核按 RM0008 §7.3.7 随之派生；`--tim-clk` 显式值优先；生成的 `spiN_write_burst` 逐字节排空 RX（RM0008 §25.3.5 单缓冲接收，F-178） | `python scripts/gen_periph.py --help` |
| `scripts/capture_sim.py` | sim 采集会话：qemu-system-arm 直接加载 elf（无板闭环，F-150） | 经 `verify.py` 消费（见「无硬件快速体验」） |
| `scripts/mcp_server.py` | MCP 接入：六工具有界包装（见下节），零业务复制 | 见「MCP 接入」节 |

### 真机工具（需板子/探针）

| 工具 | 一句话 | 典型命令 |
|---|---|---|
| `scripts/verify.py` | 闭环编排：build→analyze→flash→capture→判定，`--json` 结构化输出（配置 sim 后端时无硬件） | `python scripts/verify.py --project <工程根> --json` |
| `scripts/release.py` | G0→G3 门禁发布：全绿才打 tag，记录含双重哈希锚 | `python scripts/release.py --project <工程根> --tag vX.Y.Z --dry-run` |
| `scripts/hardfault.py` | HardFault 现场：寄存器 + 符号表定位出错函数 | `python scripts/hardfault.py --json` |
| `scripts/esp_runtime.py` | ESP32 三后端封装：idf.py build / esptool flash / UART 定时窗采集 + esp_panic 文本标记（F-174） | 经 `verify.py` 派发（`builder=idf`） |
| `scripts/serial_*` / `openocd_*` | 串口与探针底层族（RTT/GDB/telnet） | `python scripts/<name>.py --help` |

## MCP 接入（AI agent 第一接口）

把六个核心工具包装成有界 MCP 工具（stdio transport）：`run_verify` /
`lint_expectations` / `gen_peripheral` / `rm_lookup` / `diagnose_hardfault`
（仅解析不触探针）/ `doctor`。安全设计与 agentic-hil 同源：工具=对现有脚本的
子进程透传（零业务逻辑复制，CLI 仍是唯一事实源）、入参白名单校验、
**不给 agent 任意 shell**。

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
Windows `msvcrt.locking` / POSIX `flock` 的 OS 级文件锁）——同一探针/板子
同时只被一个 agent（或同一台机的另一份 clone）占用；进程崩溃 = OS 自动
放锁，无 PID 探活、无超期回收。锁粒度当前为**机器级**（设备名固定
`stlink`，F-174 后 ESP 运行同样经这把锁排队——宁多排不错排；多探针细粒度
列为后续）。冲突方收到 `resource_busy` + 持有者
purpose/获取时间，`--lease-wait N` 可有界等待。它与 `.workbench/state.json`
的写锁（F-127，防数据竞争）是两层，互不替代。

## 项目结构

```text
embedded-toolkit/
├── scripts/            # 40+ 个 .py（入口 verify.py；共享层 wb_common + runtime_common
│                       #   单一事实源 + wb/openocd/serial 三 runtime，F-029；
│                       #   legacy/ 空目录占位，Keil 退役区已拆 archive，F-067b）
├── tests/              # unittest 回归套件（纯 mock，Win/Linux 全绿）
├── data/               # 知识库：55 外设参考 JSON + 架构常量档（arch-facts，F-179）+ 已知限制
│                       #   （ARMCC 错误码库 keil-error-db.json 已随 Keil 退役区拆 archive）
├── config/             # 串口/探针族的环境级配置（keil.json 退役后已拆 archive）
├── hooks/              # 固件工程侧三条 C 铁律（禁 malloc / 禁逻辑层 HAL_Delay / volatile 告警）
├── templates/          # FSD 需求规格书模板 + RTT 版 HardFault 现场 handler
├── machine.json        # 本机工具链路径（不入库；模板 machine.example.json）
├── CHANGELOG.md        # 全账本：条目可对到 commit
└── VERSION             # 当前 0.6（版本唯一事实源 = VERSION 文件，经 wb_common.toolkit_version() 读取）
```

## 质量与验证

- 回归套件：`python -m unittest discover -s tests` 全绿为准（例数随修复增长，
  以实跑为准）；CI 每 push 必跑 9 job（+1 测试报告 check run）：unittest
  四腿矩阵（ubuntu×windows × Python 3.10/3.12）、coverage-gate（棘轮下限，
  只升不降；F-176 起与金丝雀同装声明依赖，套件跨 job 等价）、lint（ruff E/F）、
  coverage-lint（零覆盖清单 --strict）、syntax-smoke（ubuntu 真实 arm-gcc
  编译生成物）、sim-demo（ubuntu qemu 无板端到端闭环 + dorny/test-reporter
  出 "Sim Verify Results" check run）；真机冒烟另有 `hw-smoke.yml` 门控形态
  （self-hosted runner 就绪才跑）
- 修复纪律：**修 bug 必带回归测试**；写回型工具的默认参数路径必须有测试
- 治理机制：外部异构智能体代管两轮——机制本身（分支起点核查、guard 禁线、
  换回五步、fresh-check 外审）持续演进；完整对账链在维护者私有仓
  `<维护者私有仓>/docs/handoff/`，不在本仓
- 发布记录可信度：`release_audit` 对既有真实记录跑 CLEAN/预期 WARNED，
  篡改场景（换清单/搬记录）由测试固化

## 已知限制

每条按 **影响 / 规避 / 详情** 三段陈述；处置过程与证据链一律在
[CHANGELOG](CHANGELOG.md)（本区只登记"今天仍存在的限制"）。

- **Linux 真机路径未验证（F-031，部分闭合）**
  影响：Linux 上真机烧录/采集不能开箱即用（进程终止/信号/创建标志类平台差异
  属盲区；已知崩溃点已由 F-027 修除并带 mock 钉）。规避：Linux 侧照常跑测试套、
  离线工具与 sim-demo 无板闭环（CI 每 push 实证）；欲补真机验证欢迎开 issue。
  详情：CHANGELOG F-027 / F-031 / F-164。
- **serial mux 依赖 socat（F-032，平台限制声明）**
  影响：`serial_mux`（PTY 虚拟串口分光）仅 Linux/macOS；Windows 上 `mux_start`
  体面拒绝（`socat_missing`），整个 mux 族不可用。规避：直连物理串口即可满足
  verify 全链——RTT/semihosting/UART 采集后端均不经 mux 层。
  详情：CHANGELOG F-032、`scripts/serial_mux.py` 头注。
- **OpenOCD cfg 参数化已收口（F-170 提前行权，WB-20260919-06，待真机回归合入）**
  影响：原 7 处硬编码 `interface/stlink.cfg` + `target/stm32f1x.cfg` 已收敛到
  `runtime_common.resolve_openocd_cfg` 单一事实源（默认行为逐字节不变）。
  覆盖：工程 `.workbench/config.json` openocd 段 / 工具库 `config/openocd.json`
  的可选键 `interface_cfg` / `target_cfg`（优先级 显式参数 > 工程 > 工具库 >
  内置默认；类型非法显式报错不回落）。规避：不配置 = 行为与收口前逐字节一致。
  合入门禁 = 维护者真机全链回归（唤起条件"第二 ARM 板型/F-031"未满足，本单
  系提前行权）。详情：CHANGELOG F-170 / 契约变更段。
- **v0.5 发布记录 R7 永久 FAILED（F-169，登记语义）**
  影响：`release_audit --project stm32f103-mpu6050-oled --tag v0.5` 预期恒
  FAILED（历史 autocrlf 切换致工作树/入库字节永久错位，构造性证据坐实，
  非篡改）。规避：勿当新伤；其余发布记录不受影响，处置=不重锚不改记录。
  详情：CHANGELOG F-114 / F-169。
- **F-174 开账**：deferred 票 F-174a（`_write_last_build` 无锁读改写，单进程
  持锁场景伤害有限）/ F-174b（`build/*.bin` glob 双 OTA 分区表下可能选错展示
  值，烧录不受影响）终审全裁"可留"；后续票两张——终审波 N-3（ESP 空捕获提示
  语换串口/波特率/复位窗口径）/ N-4（`physical_gate` 纳入后端闸，现默认关断
  无实害）。详情：CHANGELOG F-174 收口段。
  **2026-09-25 订正（✅ F-188，WB-20260925-02）**：后续票两张已收口——N-3 空捕获
  兜底文案按 `_esp_backend_mode` 分流（ESP 口径=串口/波特率/复位窗，manifest/legacy
  两处）· N-4 `physical_gate` 入后端闸（ESP 下 skipped+reason，闸在 verify.py 调用
  侧）；F-174a/F-174b 两笔"可留"维持原判。详情：CHANGELOG F-188 节。
  **2026-09-26 订正（✅ F-190，WB-20260926-01）**：F-174a 已随 H-1 闭合——
  `_write_last_build` 改调 `runtime_common.update_state_entry`，实读源码核实其锁
  语义覆盖原判四病中的三病（无锁 RMW→持锁读改写 F-127 · truncate 非原子→.tmp+
  os.replace 原子替换 F-020 · 损坏清空→.corrupt 隔离 F-019），第四病（嵌套
  `artifacts` 键缺失=H-1 病灶）同单修除；F-174b（bin glob 双 OTA 分区表选错展示
  值）"可留"维持原判。详情：CHANGELOG F-190 节。
- **GAP-F-19（2026-09-25 登记，暂缓）**：capture/flash 两处 backend 派发缺省值
  （`cap_backend` 缺省 semihosting、`flash.backend` 缺省 openocd）不受
  `_esp_backend_mode` 约束——builder=idf 而漏配 backend 键的混配工程仍会走
  OpenOCD 路径。定性=F-174"按 backend 键分流"的设计面（非 I-1 类无条件步骤，
  F-007 守卫在烧录前拦截无 hex 场景），非紧急。裁定=暂缓登记，
  **唤起条件 = WB-20260925-01 整批复审报告落账**（若带出更多同类缺省派发面，
  合并一次裁决收口票；否则单独立项）。出处：CHANGELOG F-188 节"只列不改"。
  **2026-09-26 收口（✅ F-190，WB-20260926-01）**：维护者裁定 fail-fast 落地——
  三标记任一在场而 builder / flash.backend / capture.backend 三键不齐或取值非法，
  verify 在任何构建/烧录动作之前 ERROR→exit 1（规则本体
  `runtime_common.esp_backend_config_errors`，与 `esp_backend_mode` 同源单一事实）；
  复审带出的 release G0.5 swd_probe 漏闸（M-1）同票合并收口。四存量 ESP 工程
  （esp32-hello / esp32s3-hello / s3-voice / cam-eye）三键全显式，实跑零存量破坏。
- **GAP-F-20（2026-09-26 登记，暂缓）**：共享向量 TIM 的 ISR 名生成面——
  `gen_periph.py` 向量名逻辑仅对 TIM1 特判，TIM9/12/13/14 等共享向量外设生成的
  `TIM9_IRQHandler`/`TIM9_IRQn` 等**不是 CMSIS 实名**（`TIM1_BRK_TIM9_*` 族），
  按生成物定义的 ISR 不会接进向量表——**F-086 同族 B 类静默**（编译链接全绿、
  ISR 永不执行）。ISER 位号面已由 F-191 修对，本条只剩**向量命名域**。危害面以
  "非 C8 目标 + 手工取用生成物"为界（TIM8~14 均 `available_on_c8=False`）。
  修法需 gen-maps 增 irq-name 域 + vec 命名逻辑改造，非杂项量级。
  裁定=暂缓，**唤起条件 = 样例工厂二期 / 非 C8 目标立项 / 下次动 gen-maps irq 域设计**。
  出处：CHANGELOG F-191 节 P 面（WB-20260926-02 §六 P-1）。
- **WB-05 审查残量·生成器与数据面（2026-09-26 对账确认仍在，M/L 各一包；
  对账=WB-20260926-04 报告 §一，入册经维护者批准）**
  影响：① `phase_minus_one` 芯片支持检查不消费 `available_on_c8`——C8T6 不可用
  的 22 个 KB 外设（TIM5/8/9、ADC3、DMA2、FSMC、SDIO 等）前置闸假 OK，白耗一轮
  HIL（WB-05 M-1）；② `gen_periph` 引脚零校验（PA20/PA12 同半字节静默碰撞、
  `--pin P` 裸 IndexError、小写 pa0 产 IOPaEN，WB-05 L-1）；③ 生成的 i2c 帮手
  引用 `error_chain_t/ERR_PLAIN` 但不发射定义，照抄即编译失败（WB-05 L-4）；
  ④ `svd_to_json --periph` 流式路径不解析 peripheral 级 derivedFrom（CMSIS 属性
  风格），寄存器表空且与 `--all` 劈叉、零告警（WB-05 M-8）；⑤ `svd_to_json
  merge_into_ref` 对 KB 主文件截断式裸写，中途失败即损坏 `data/stm32f103-ref.json`
  （WB-05 M-9）；⑥ SVD 位域 lsb/msb 风格静默丢弃、基字段回填不认 bitRange
  （WB-05 L-3）。规避：Drafter 前置闸结果人工复核 `available_on_c8`；生成物人工
  过目；SVD 导入一律走 `--all` 并人工抽查 derivedFrom 外设；merge 前手动备份
  ref.json。详情：WB-20260919-05 报告 §一；对账单报告 §一（现树行号）。
- **WB-05 审查残量·健壮性与防篡改面（2026-09-26 对账确认仍在）**
  影响：① 管道编码漏网三处——`hardfault.py`/`handoff_guard.py`/`release_audit.py`
  输出无 force_utf8（cp936 控制台下 hardfault 步骤 diagnosis 乱码实测复现）
  （WB-05 M-4）；② `junit_xml` 不净化 XML 1.0 非法控制字符，脏 detail 产出非法
  XML 且信封 ok=True（WB-05 M-5）；③ `release_audit` R8 只查批准时间戳非空
  （手工填值即过）、R6 不查工作树脏状态——与头注"手工改值视同篡改"承诺不符
  （WB-05 M-6）；④ `evidence_export` 对改坏的发布记录抛未捕获 AttributeError，
  CI `if: always()` 步骤假红（WB-05 M-7）；⑤ `release.py _gcc_version` 配了
  `gcc_path` 即拼 `arm-none-eabi-gcc.exe`，Linux 上恒 unknown（WB-05 L-7，
  F-190 只分流了 ESP 面）；⑥ `mcp_server.resolve_project` 对库根本身不设防
  （下游 preflight 兜底，无实害语义落空）（WB-05 L-8）；⑦ `doctor` fixture 漂移
  哈希经解码-再编码往返，非法 UTF-8 误报漂移（WB-05 L-9）；⑧ `handoff_guard`
  L2 豁免按任意层目录名匹配，`docs/tests/x.py` 全豁免（WB-05 L-10）；
  ⑨ `fsd_coverage` config 损坏静默回退默认 FSD 且 notes 人读不可见（WB-05 L-11）；
  ⑩ `phase_minus_one` fixed_pins 损坏谎报"没有占用表"（fail-open）、BLOCKED
  退出码恒 0（WB-05 L-2）。规避：中文 Windows 下以 UTF-8 模式跑 verify；发布
  记录不手工编辑；Linux 发布机 machine.json 留空 gcc_path。
- **Note 面留档（2026-09-26 对账）**：`feedback_db` 多进程 RMW 无锁（单会话假设
  维持，WB-05 N-1）；`serial_send` hex 模式 `A0xB` 类输入剥转损坏（WB-05 N-3）。
  引用防呆：WB-05 与 01 报告存在**同号异病**（M-1/H-1/L-2/N-3/N-4 五对），引用
  必须带报告名前缀（对账单 §六）。
- **GAP-F-13 现势口径订正（2026-09-26，对账单 §三建议采纳）**：全局打桩计数现势
  一律以 `tests/test_stub_ratchet.py` BASELINE 为唯一事实源（**73 键/157 处/38 文件**，
  AST 判据、机检守卫）；历史口径 98 处/22 文件（F-184）与 102 处/23 文件（01 报告
  粗扫）退役为史料。"按需收窄、不批量清扫"裁决维持。
- **ref.json 数据面 GAP-D 收口状态（F-179，WB-20260920-05）**
  影响：`data/stm32f103-ref.json` 的 `bus` 字段曾与外设 RCC 使能位归属相反
  （TIM9 记 APB1、TIM12/13/14 记 APB2）；`_relationships` 的 IRQ 号只覆盖 12 个外设；
  IWDG KR 魔数 / FLASH KEYR 魔数 / CRC poly·初值 / PLLMUL 编码表 / USBPRE 位 /
  SDIO PWRCTRL 位域 / DBGMCU CR 位表等架构常量**未登记**（GAP-D-1/2/3/4/5）。
  规避：消费方一律以 RCC 位名数据为准；需要架构常量时读新档
  `data/stm32f103-arch-facts.json`（**每条带 source**，取值三型：
  RM0008 节号 / CMSIS 文件行 / arch-constant 依据句）。
  现状：`bus` 已修正并加**类级防线**（`tests/test_ref_bus_crosscheck.py` 从 ref.json
  自身的 ENR 位名反推期望集，覆盖 46 外设）；`_relationships` IRQ 12 → 21；
  架构常量入册 48 条（`tests/test_ref_arch_facts.py` 钉结构+出处+CRC 防循环自证）；
  dbg 样例补做（`examples/f103-dbg/`，工厂巡检 56 绿）。**仍未入册**（本地无 RM0008 /
  数据手册可锚，宁缺毋滥）：CAN/ADC3/TIM5/TIM8/TIM9/SDIO/FSMC/DMA2 引脚映射、
  FSMC BCR·BTR 位名、USBPRE 与 SDIO PWRCTRL 的值语义。
  详情：CHANGELOG F-179 / WB-20260920-05 报告 §8 弃登清单、§9 新发现缺口。
  **2026-09-26 订正（✅ F-191，WB-20260926-02）**：F-179 的消费面随动缺口已收口——gen-maps 第二套平行 bus/IRQ 事实源 `tim_bus`/`tim_irq` 补齐
  `_relationships` 全部 11 个 TIM（值全数 ref.json 反查逐键互证，M-2 实录
  的 `--timer TIM9` 三层错生成随之修除）+ 类级互证钉
  `tests/test_genmaps_ref_crosscheck.py` 防同类缺键 + `--timer` 入参收口
  （未登记名 ERROR→exit 1，合法集随文案，F-185 P-3 同款）。详情：
  CHANGELOG F-191 节。
  **2026-09-26 补源订正（F-189，WB-20260925-03）**：弃登清单三态更新——
  **语义已锚**：USBPRE 值语义（0=PLL÷1.5 / 1=不分频，RM0008 §7.3.2 p102）与
  SDIO PWRCTRL 四态语义（00=Power-off / 11=Power-on，RM0008 §22.9.1 p607）
  经 st.com 官方原文逐字引文入册 `arch-facts.json`（出处增第四型
  `web:<文档号>:<节/表号>:<页>`，seed HAL 宏交叉验证一致）；**FSMC 位名已入册**：
  新 `fsmc` 节 BCR 15 + BTR 7 位名+语义（RM0008 §21.5.6，逐位标
  `cmsis_crosscheck`；F-179 时"seed 无 FSMC 位定义"系 grep 漏通配形态的误判，
  seed 实有 f103xg.h:5210-5317 全套）；**映射仍弃登**：8 项请求外设仅 CAN 在
  DS5319（F103x8/xB）覆盖内，引脚映射文件格式提案 + CAN 样本四行在
  WB-20260925-03 报告 §T2，**待维护者批准后另单落盘**；TIM5/ADC3/TIM8/TIM9/
  SDIO/FSMC/DMA2 在 DS5319 引脚表零行，弃登维持（需高密度数据手册另单）。
  详情：CHANGELOG F-189 / WB-20260925-03 报告。
  **2026-09-26 落盘订正（✅ F-193，WB-20260927-01）**：三态再更新——
  **CAN 已入册**：新档 `data/pin-mapping-f103.json`（**LQFP48/xB 封装切片**，
  `tests/test_pin_mapping.py` 结构/source 前缀/引文对账完备三面钉）收 CAN
  四行：PA11=CAN_RX、PA12=CAN_TX（alternate）+ PB8=CAN_RX、PB9=CAN_TX
  （additional=AFIO 重映射态），锚 `web:DS5319:§3:Table 5:p31/p33`；
  **DS5319 已升版 Rev 18→Rev 20**（Table 5 重排为多封装宽表），F-189 旧锚
  三处随今日直抓订正：节号 §8→**§3**、页位 p27/p28→**p31/p33**、PA11/PA12
  的 LQFP48 脚号 33/34→**32/33**（F-189 疑列读串；CAN 功能/列位语义不变）；
  **DS5318 授权已用、结论=查无此脚**：高密度数据手册实为 **DS5792**
  （DS5318 系文档号误记），其封装自 64 脚起（§2.1 逐字 from 64 pins to
  144 pins）、无 48 脚封装表，ADC3/TIM8/SDIO/FSMC 信号脚（PF6-10、PC6-12+
  PD2、PE-PG，且 Table 6 注 11 明言 LQFP64 亦无 FSMC）不在 LQFP48，TIM5
  信号脚（PA0-3）在而无 HD 器件以 48 脚封装出货（官方表无行不硬造），DMA2
  无外引脚——7 外设弃登维持。详情：CHANGELOG F-193 / WB-20260927-01 报告。
- **py3.10 语法地板（F-181，WB-20260921-02 已加钉）**
  影响：CI 有 py3.10 腿，而 **PEP 701** f-string 写法（3.12 才放宽：表达式区同类
  引号 / 反斜杠 / 跨行与注释）在本机 3.14 全绿、到 3.10 腿上整腿炸。
  ⚠ `ast.parse(feature_version=(3,10))` **不是有效判据**（对 PEP 701 探针不报错，
  放宽在 tokenizer 层）。
  规避/守卫：`tests/test_py_floor.py` 用 `tokenize` 扫 `scripts/*.py` + `tests/*.py`
  的三类违规，夹具自证（违规必咬 / 合法必零报）；<3.12 解释器上**显式 skip**，
  由 CI 3.12 腿承接。
  详情：CHANGELOG F-181 / WB-20260921-02 报告。
- **hooks 行为探针依赖可用 bash（F-181，WB-20260921-02 已加固）**
  影响：`hooks/*.sh` 是 shell 脚本，探针需 bash。Windows 上 `which("bash")` 可能
  命中 `System32\bash.exe`（WSL 启动器，未装 WSL 时一律 rc=1）。
  规避：解析器逐候选探测，**命中 system32 一律跳过继续向后找**（Git for Windows 等）；
  全部不可用则 `skipTest` 并输出候选/rc 诊断（**不静默假红**）。安装 Git for Windows
  并把其 `bin` 置于 PATH 即可正常执行。
  详情：CHANGELOG F-181 / WB-20260919-05 报告 §六 GAP-ENV-2。
- **有意搁置**：UART 串口补丁的发布门禁脆弱性（成本/收益不立项）。
  详情：CHANGELOG 对应裁决记录。
- **已闭合归档账**（不在此展开）：审核 M-4 ✅ F-162 · L-4 覆盖洞 ✅ F-163 ·
  gcc_build 预检平台化 ✅ F-164 · 计时脆弱钉 ✅ F-165（同批 F-166 py3.10 双腿
  + stderr pump）· CI 依赖跨 job 等价 ✅ F-176 · uart 采集桥接板握手线释放
  ✅ F-177（初代 esp32 真机双 PASS + S3 回归同日补票双 PASS）· Agent 正门与数据
  信任包 ✅ F-178（MCP boolean argv / cube_usercode backup-restore 事务化 /
  spi `write_burst` 排空读 / verify 证据表 `uart` 键）· MCP 正门收口
  ✅ F-183（rm_lookup 位置投影 / project schema 尾逗号 / mux 打桩收窄 / GAP-F-11 空值口径）· 打桩卫生收官
  ✅ F-184（GAP-F-10 os._exit 收窄 / GAP-F-13 全仓清点与"按需收窄"裁决 / GAP-F-14 消音）· 拍板批落地
  ✅ F-185（P-3 ERROR→rc=1 / D-6 核心块 bus="core"+封闭集钉 / P-1·P-2·F-13 结案追认）· clock 宏名根治
  ✅ F-187（GAP-F-16 BDCR 不存在的宏 → KB 键表事实源；F-186 数据激活，取证于 WB-20260922-02）· ref.json 数据面收口
  ✅ F-188（N-3 ESP 空捕获文案按后端分流 / N-4 `physical_gate` 入 `_esp_backend_mode` 闸）· F-174 后续票收口
  ✅ F-179（GAP-D-5 bus 反转 + RCC 位名类级防线 / `_relationships` IRQ 9 条逐条锚
  CMSIS xg.h / `stm32f103-arch-facts.json` 48 条带出处入册 / f103-dbg 样例解锁）· MCP
  整型参数 argv 收口 ✅ F-180（GAP-F-1：非 boolean 参数值一律 str 化入 argv，6 个整型
  参数 `run_verify.timeout` + `gen_peripheral` ch/freq/duty/baud/speed 由 100% 不可用转可用）·
  测试卫生包 ✅ F-181（GAP-F-2 py3.10 语法地板钉 + GAP-D-9/D-1 槽位注记随动 +
  GAP-ENV-2 hooks bash 解析加固 + GAP-ACC-1 backup 交换回滚支补钉）· KB 消费面随动 ✅ F-191（gen-maps tim_bus/tim_irq 补齐 11 TIM + 类级互证钉 + `--timer` 入参收口 / rm_lookup 人读 desc 三处 + clock_enable 死支反查） · 护栏棘轮与杂项捆 ✅ F-192（全局打桩静态棘轮 L-2 收口：157 处/73 键快照 + 新增即红 + EXEMPTS+note + 双枪 / rm_lookup `--recipe` 人读 KeyError / release openocd_exe 缺键分流 / uart SerialException 已收行入账 / verify swd_probe 死导入删）
  ——证据链
  （run/PR/钉子清单）均在 CHANGELOG 对应票。

> **F-021~F-030 已在本轮收口**（原子写收口包 / R7 双布局认路 / RTT 平台守卫 /
> 孤儿链删除 / 三 runtime 契约统一 / 头图刷新），逐条处置记录与证据 commit 见
> [`CHANGELOG.md`](CHANGELOG.md)。新发现请开 Issue。

## 文档索引

- [`CHANGELOG.md`](CHANGELOG.md) — 版本账本（每条对到证据 commit）
- [`templates/fsd-template-stm32.md`](templates/fsd-template-stm32.md) — 需求规格书模板
- [`templates/hardfault_rtt.c`](templates/hardfault_rtt.c) — RTT 工程 C 级
  HardFault 现场 handler（F-115）：新工程接入 = 复制到 User/ + Makefile
  C_SOURCES 加一行 + 删除工程自有 `HardFault_Handler` 死循环桩让位强符号
- Keil 退役区唤起（archive 物理副本）: `<d-claude-root>\archive\
  embedded-toolkit-keil-legacy-20260905\README.md` — 2026-09-05 F-067b
  起 Keil 退役桥（keil_build / keil_analyze / keil_project +
  data/keil-error-db.json + scripts/error_db_grow.py + config/keil.json）
  已从仓内拆出；按需唤起见该 README（也可走 `EMBEDDED_TOOLKIT_KEIL_ARCHIVE`
  环境变量指 archive 路径）
- [`docs/handoff/` `docs/superpowers/` `skills/fresh-checker/` `AGENTS.md`
  `HANDOFF-AGENT.md`](#) — 已于 0.4 边界决策迁维护者私有仓
  `<维护者私有仓 embedded-handoff>`，公开工具库不含维护者 ↔ Agent 协作私约

## 生态位

同类项目各有所长：agentic-hil 以有界 MCP 工具 + 硬件租约 + plan 门禁见长，
agentic-embedded-lab 做仿真控制面（claim + fidelity 证据分级），pytest-embedded /
Renode 把仿真做成平级判定后端，hardci / jlink-mcp 验证了 MCP 分发路径。

本仓的独特处不在单点能力，而在**完整治理链**——同类项目普遍假设"固件已存在
只管测"，本仓从需求一路管到事后审计：

1. **四态判定 + XPASS 判红**——期望清单里 `xfail` 欠条落地瞬间判红，杜绝
   "顺便实现了"静默混入
2. **FSD 对账**（`fsd_coverage.py`）——需求 ↔ 断言双向对账，xfail（欠条）与
   waived（豁免）两级不混用
3. **G0–G3 发布门禁 + R1–R8 事后审计**——全绿才打 tag；证据等级四档
   （`hardware_validated` / `simulation_validated` / `static` /
   `production_approved`），仿真/静态证据进不了发布记录，发布后篡改在
   契约哈希锚（R7）与批准留痕（R8）下现形
4. **反馈校准**（`feedback_db.py`）——修复事件落账，按流水线长出准确率校准
5. **寄存器知识库 + 代码生成**（`rm_lookup.py` + `gen_periph.py`）——
   55 外设参考数据直接生成寄存器级初始化代码，AI 生成物先过五重门控再进编译
6. **构建错误知识库**——gcc/ARMCC 错误自生长，修复纪律靠回归测试钉住

## 路线图

### 已落地/立项方向（2026-09-12 同类调研，见 CHANGELOG 工单二系列）

调研来源除上述项目外，另按总工单 v2 D-3 点名登记一条学术引用（闭环评测论文）。
原并列登记的 arXiv:2509.09970 已于 2026-09-14 联网核实并**撤销**：该编号实际
解析为 Ultra-R1（文本生成图像推理模型，cs.CL），与嵌入式闭环验证无关——
登记时网络不可达、照录工单原文未验，属引用错误（F-167 记账）。

- **MCP 接口**——已落地：`scripts/mcp_server.py` 六工具有界包装（白名单校验、
  零业务复制、不给 agent 任意 shell）；调研来源 agentic-hil / hardci / jlink-mcp
- **无板仿真闭环**——已落地：`capture.backend: "sim"`（qemu-system-arm +
  semihosting，`examples/sim-demo` 即跑）；调研来源 pytest-embedded / Renode；
  spike 记录 F-149（含 M-profile SYS_EXIT 0x18 不退出的实测坑）
- **多 MCU（ESP32）**——已落地最小闭环（F-174，09-16 试点 / 09-18 合入）：
  idf/esptool/uart 三后端 + 真机双 PASS + 后端闸与 port/chip 白名单；
  剩余非目标按立项裁决后置：WiFi/BLE、probe-rs 调试、panic 符号化、
  xiaozhi 类业务工程接入
- **分发形态**（PyPI / uvx / Claude Code 插件，"一行安装"）——**暂缓（2026-09-14）**：
  曾立项待做 spike（风险点在 `data/`、`VERSION`、machine.json 的包数据定位
  策略），经评估当前无外部用户、git clone 自用形态够用，且其服务对象"开源
  推广"本身是待评估期权——降级为暂缓，**唤起条件 = 决定对外推广 toolkit 的
  那天**，届时先做 spike 再立项；调研来源 agentic-hil / hardci
- **真机 CI 冒烟**——已落地（门控形态）：`.github/workflows/hw-smoke.yml`
  仅在仓库配置了 self-hosted runner（`HW_RUNNER_READY` 变量）时运行；
  调研来源 jlink-mcp 的真机徽章 + ESP32/树莓派 runner 案例
- **演示录屏**（一次 verify 从烧录到判 PASS 的全过程，asciinema/板载实录）——
  **backlog 待补**：README 现以逐字实录（「效果预览」）为证据，不用摆拍素材；
  真实录好后插入本节上方

## 贡献

请先读 [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md)（环境准备 / 测试纪律 / 禁区）：

- **Bug / 功能请求**：用 [Issue 模板](.github/ISSUE_TEMPLATE/) 提报（模板会要求
  工具链版本与 OS/Python 信息；verify 相关问题请附 `verify.py --json` 完整输出，
  失败现场另有 `.workbench/build/last_failure.json` 可一并贴上）
- **PR**：按 [PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) 填写；
  提交前 `python -m unittest discover -s tests` 全绿并把统计行贴进 PR；
  修 bug 必带回归测试
- **安全问题**：请勿开公开 issue，按 [SECURITY.md](SECURITY.md) 私下报告
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
