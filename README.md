# embedded-toolkit

[![CI](https://github.com/xujiujiu0628/embedded-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/xujiujiu0628/embedded-toolkit/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)

**AI 写嵌入式固件的闭环验证工作台：代码可以由 AI 生成，但"算不算对"由机器说了算。**

针对 STM32F103（可扩展）的 GCC 工具链，把 `需求契约 → 构建 → 烧录 → 真机输出采集 →
期望判定 → 发布门禁 → 反馈落账` 串成一条全自动判定链——AI 生成的固件必须在自己
板子上打印出符合契约的证据，才有资格打 tag。它解决的核心问题是：**LLM 写固件
无法自证正确**，而人眼盯串口又慢又漏。

## 特性

- **四态期望判定**：`expectations.json` 契约驱动，PASS / XFAIL / XPASS / FAIL，
  意外通过（XPASS）强制判红——"碰巧对了"也算错
- **真机证据采集**：RTT / semihosting 双后端抓取固件 printf 输出，数值断言
  （正则 + capture_group + min/max）直接编进契约
- **发布门禁 G0→G3**：git clean → SWD 连通预检 → clean rebuild 重跑判定 →
  xfail 翻转 → 落记录打 annotated tag，任一环失败自动回滚
- **双重取证锚**：hex 字节哈希锚定"烧的是什么"，契约哈希（sha256）锚定
  "拿什么判的绿"——发布记录可被 `release_audit` 事后逐条重算
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

对应的机器判定输出（`verify.py --json` 节选，全文真实可回放）：

> 注：本段为 **0.2 时期**的真机实录，`toolkit_version` 字段如实保留当时的 `"0.2"`
> （不随版本推进改写历史输出）。0.3 的输出字段结构与此一致，仅版本号与哈希值不同。

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
需求(FSD/expectations.json) → 生成(Claude + review-code 对抗审查) → 构建(gcc_build/verify.py)
  → 真机判定(RTT/semihosting 采集 printf) → 门禁(release.py G0-G3, 全绿才打 tag) → 落账(feedback_db.py 校准)
```

三个设计支点：

1. **判定外置**——"对不对"不写在 AI 的自觉里，写在版本化的契约文件里；AI 改代码
   可以，改契约会在发布审计（R7 哈希锚）里现形。
2. **证据优先**——每条期望必须对应真机打印的字节（正则匹配 + 数值区间），
   `HAL_OK ≠ 字节正确` 是本仓库用一个月黑屏 OLED 换来的教训。
3. **异构审查**——工作台的维护者（AI）也会被换无上下文、不同模型家族的
   外部智能体审计，`handoff_guard` 机器强制其不碰硬件与禁区；两轮实战的完整
   发现/对账记录在 [`docs/handoff/`](docs/handoff/)。

## 环境要求

| 依赖 | 用途 | 备注 |
|---|---|---|
| Python **3.10+** | 全部脚本 | 标准库为主，串口族需 `pip install -r requirements.txt` |
| arm-none-eabi-gcc | 构建 | GNU Arm Embedded Toolchain（或 xPack） |
| GNU make | 构建 | Windows 推荐 MSYS2 的 make.exe |
| OpenOCD | 烧录/RTT/semihosting 采集 | 推荐 xPack 发行版 |
| ST-Link + STM32F103 板 | 仅真机步骤 | 无板也能跑测试、lint、审计、代码生成 |

平台现状：**Windows 为主要开发/真机平台**（工具链预检按 `.exe` 探测）；
Linux/macOS 上测试套与离线工具全量可跑（CI 即证），真机构建路径未验证、欢迎报告。

## 安装

```bash
# 1. 克隆
git clone https://github.com/xujiujiu0628/embedded-toolkit.git
cd embedded-toolkit

# 2. 立刻可验证（无需任何配置——machine.json 缺失时自动回退模板并提示）
python -m unittest discover -s tests

# 3. 要用真机前：生成机器路径配置（machine.json 是本机文件，不入库）
cp machine.example.json machine.json   # 编辑填入 gcc_path / make_exe / openocd_exe 绝对路径

# 4. 可选：串口工具的第三方依赖
pip install -r requirements.txt
```

### 平台说明：Windows 首次跑测试的告警

如果你是 **Windows + PowerShell**，第 2 步会看到十几条这样的乱码：

```text
Warning: session_fix_cache.json , ԭļ: ...: Expecting property name enclosed in double quotes: line 1 column 3 (char 2)
```

**这是终端编码问题，不是工具失败**——测试仍会输出 `OK (skipped=1)`。成因：

- 工具链的反馈库（`error_db_grow.py` / `feedback_db.py`）发现缓存文件损坏时，**主动**把损坏文件隔离为 `.corrupt` 并重建——这是 F-020 的诚实化设计（绝不裸 traceback）
- 它向 stderr 写的中文警告，Linux 终端能正常显示；Windows PowerShell 默认 GBK 解码
- 整个流程是"预期告警 + 正确恢复"，不是 bug

判定方法：忽略 stderr 的 Warning 行，看最后一行 `OK (skipped=1)` / `FAILED` 即为测试结果。CI 跑在 ubuntu（CONTRIBUTING 平台现状节），看不到这些告警。

如果乱码让你无法读测试结果，可以强制 Python 用 UTF-8：

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m unittest discover -s tests
```

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

# 5. 发布演练（【需板子】，dry-run 不打 tag 不落库）
python scripts/release.py --project <工程根> --tag v1.0.0 --dry-run
```

## 核心工具速查

| 工具 | 一句话 | 需硬件 |
|---|---|---|
| `scripts/verify.py` | 闭环编排：build→analyze→flash→capture→判定，`--json` 结构化输出 | ✅ |
| `scripts/gcc_build.py` | GCC/make 构建后端，JSON 契约输出 + 产物登记 | ❌ |
| `scripts/release.py` | G0→G3 门禁发布：全绿才打 tag，记录含双重哈希锚 | ✅ |
| `scripts/release_audit.py` | 发布记录事后审计 R1~R7（tag 指向/hex 重算/契约锚） | ❌ |
| `scripts/expectations_lint.py` | expectations.json 提交前校验 E1~E9 | ❌ |
| `scripts/handoff_guard.py` | 外部智能体代管分支的三级禁线机检 | ❌ |
| `scripts/feedback_db.py` | 修复事件落账 + 每流水线准确率校准 | ❌ |
| `scripts/rm_lookup.py` | STM32F103 55 外设寄存器/位域速查（JSON 知识库） | ❌ |
| `scripts/gen_periph.py` | 参数 → 寄存器级 C 初始化代码 / 外设文档 | ❌ |
| `scripts/hardfault.py` | HardFault 现场：寄存器 + 符号表定位出错函数 | ✅ |
| `scripts/serial_*` / `openocd_*` | 串口与探针底层族（RTT/GDB/telnet） | ✅ |

## 工程契约（`.workbench/`）

固件工程通过 `.workbench/config.json` 被发现（从 cwd 逐级向上查找，兜底识别
旧版 `.embeddedskills/config.json`）。期望判定规则：

- `id` 唯一必填；`texts`（全 substring 命中）与 `patterns`（全正则 search 命中）二选一
- `"xfail": true` 必须携带 `xfail_reason`——待办欠债全部白纸黑字
- 数值断言：`pattern` + `capture_group` + `min`/`max` 区间
- 版本控制建议：`config.json` / `expectations.json` / `releases/` 入库；
  `build/` 与 `state.json`（可再生缓存）忽略

## 项目结构

```text
embedded-toolkit/
├── scripts/            # 34 个 .py（入口 verify.py；共享层 wb_common + runtime_common
│                       #   单一事实源 + wb/openocd/serial 三 runtime，F-029；legacy/keil/ 为退役留门区）
├── tests/              # unittest 回归套件（纯 mock，Win/Linux 全绿）
├── data/               # 知识库：55 外设参考 JSON + 错误库 + 已知限制
├── config/             # 串口/探针族的环境级配置
├── hooks/              # 固件工程侧三条 C 铁律（禁 malloc / 禁逻辑层 HAL_Delay / volatile 告警）
├── templates/          # FSD 功能规格书模板
├── skills/fresh-checker/  # 无上下文对抗审核 skill（与全局安装处双同步）
├── docs/
│   ├── handoff/        # 外部智能体代管的发现报告与对账记录（治理实录）
│   └── superpowers/    # 设计规格与实施计划档案
├── machine.json        # 本机工具链路径（不入库；模板 machine.example.json）
├── HANDOFF-AGENT.md    # 外部智能体上岗手册（权限/考卷/禁线/换回协议）
├── CHANGELOG.md        # 全账本：条目可对到 commit
└── VERSION             # 当前 0.3
```

## 质量与验证

- 回归套件：`python -m unittest discover -s tests` 全绿为准（例数随修复增长，
  以实跑为准）；CI 在 ubuntu × Python 3.10/3.12 上每 push 必跑
- 修复纪律：**修 bug 必带回归测试**；写回型工具的默认参数路径必须有测试
  （两条都用真事故验证过必要性，见 `docs/handoff/`）
- 治理机制：外部异构智能体代管两轮——机制本身（分支起点核查、guard 禁线、
  换回五步、fresh-check 外审）也在持续演进并留有完整对账链
- 发布记录可信度：`release_audit` 对既有真实记录跑 CLEAN/预期 WARNED，
  篡改场景（换清单/搬记录）由测试固化

## 文档索引

- [`HANDOFF-AGENT.md`](HANDOFF-AGENT.md) — 外部智能体代管协议（权限边界/巡检考卷/换回流程）
- [`CHANGELOG.md`](CHANGELOG.md) — 版本账本（每条对到证据 commit）
- [`docs/handoff/`](docs/handoff/) — 两轮异构审查的发现、建议与对账记录
- [`docs/superpowers/specs/`](docs/superpowers/specs/) — 设计规格档案
- [`templates/fsd-template-stm32.md`](templates/fsd-template-stm32.md) — 需求规格书模板
- [`scripts/legacy/keil/README.md`](scripts/legacy/keil/README.md) — Keil 桥退役定案与按需唤起

## 路线图

如实列出已编目的已知遗留（对外部审查的尊重：登记在册，不藏）：

- **F-031**（部分闭合）Linux 真机路径**整体未验证**——F-027 修掉的是"已知崩溃点"
  （`verify.py` RTT 分支的平台守卫），不是完成验证；进程终止/信号/创建标志类平台
  差异仍属盲区。已补 mock-Popen 平台派发钉（属性级 + kwargs 级双层），真机 Linux
  冒烟清单留待社区/后续
- **F-032**（限制声明，非缺陷）`serial_mux` PTY 虚拟串口层硬依赖 `socat`，
  Linux/macOS-only，Windows 不支持；`which("socat")` 在 `start_mux()` 最前无条件执行，
  无 socat 则整个 mux 起不来。`--no-pty` 解耦列为后续增强，未实现前不按部分功能规划
- 有意搁置：UART 串口补丁的发布门禁脆弱性（成本/收益不立项）
- 方向：多 MCU（ESP32）工具栈评估——见 docs 档案。前置项：把 `interface/*.cfg` /
  `target/*.cfg` 从硬编码（当前 `verify.py` 7 处 / `release.py` 2 处 /
  `hardfault.py` 2 处）收进 `config.json`

> **F-021~F-030 已在本轮收口**（原子写收口包 / R7 双布局认路 / RTT 平台守卫 /
> 孤儿链删除 / 三 runtime 契约统一 / 头图刷新），逐条处置记录与证据 commit 见
> [`CHANGELOG.md`](CHANGELOG.md)。新发现请开 Issue，或走 `docs/handoff/` 代管流程登记。

## 贡献

请先读 [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md)（环境准备 / 测试纪律 / 禁区）：

- **Bug / 功能请求**：用 [Issue 模板](.github/ISSUE_TEMPLATE/) 提报（verify 相关
  问题请附 `verify.py --json` 完整输出）
- **PR**：按 [PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) 填写；
  修 bug 必带回归测试
- **安全问题**：请勿开公开 issue，按 [SECURITY.md](SECURITY.md) 私下报告
- 社区行为准则见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## License

[MIT](LICENSE)
