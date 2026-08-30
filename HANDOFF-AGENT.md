# 交接文档：embedded-toolkit → 外部智能体代管期

> **本文读者**：被用户请来独立检查/改进本工作台的智能体（如 Z code）。你没参与过它的演进——
> 本文是你的唯一上手材料，读完 §1-§5 即可开工。**主控（Claude Code）代管期不介入**，换回见 §6。
> **上岗时间戳**：2026-08-30 14:48 +08:00（§6 越域核查以此为界）｜首现代管者：Z code｜分支：`handoff/zcode-20260830`
> 本文不含任何凭据；工作台不需要凭据。**不要去翻找密钥/token 类文件。**

## 1. 工作台是什么

嵌入式（STM32F103/GCC）的 AI 闭环开发工作台：**代码由 AI 生成，但"算不算对"由机器说了算**。
五流水线：

```
需求(FSD/expectations.json) → 生成(Claude + review-code 对抗审查) → 构建(gcc_build/verify.py)
  → 真机判定(RTT/semihosting 采集 printf) → 门禁(release.py G0-G3, 全绿才打 tag) → 落账(feedback_db.py 校准)
```

| 位置 | 是什么 | 代管期权限 |
|---|---|---|
| `<工作区根>\embedded-toolkit`（本仓） | 引擎房：脚本/门禁/测试/知识库 | **唯一可写域** |
| `<工作区根>\stm32f103-adc-oled` | 现役工程，v1.1.0 | 只读（只进建议单） |
| `<工作区根>\stm32f103-button-toggle` | 现役工程，v1.0.0 | 只读（只进建议单） |
| `C:\Users\<用户名>\.claude\skills\` | 全局 skill：review-code / fresh-checker / feedback-log / review-hardfault | 只读（只进建议单） |
| `<工作区根>\.claude\`、`<工作区根>\CLAUDE.md` | 工作区 hooks 与结构规则 | 只读（只进建议单） |

本仓内部：`scripts/`（28 个脚本，入口 verify.py，默认 builder=gcc）、`tests/`（**47 测试**，
python -m unittest）、`data/`（stm32f103-ref.json 55 外设 + 错误库）、`hooks/`（3 条 C 代码铁律检查）、
`skills/fresh-checker/`（canonical 镜像，与全局那一份**双处须同步**）、`templates/`、`machine.json`、
`docs/superpowers/{specs,plans}`（设计档案）。blink 工程已退役归档，勿按现役对待。

## 2. 已验证机制与有意决策——**勿重做、勿当 bug 报**

| # | 机制/决策 | 证据（可 `git show`） | 备注 |
|---|---|---|---|
| 1 | expectations.json 四态判定（PASS/XFAIL/XPASS/FAIL），XPASS 强制判红 | e96718b(规格) + verify.py | legacy 工程回退行为是有意的零影响设计 |
| 2 | 发布门禁 G0→G0.5(SWD 预检)→G1(clean rebuild 重跑)→G2(xfail 翻转)→G3(记录+tag+失败回滚) | 83445ed、9594dbb | `--allow-xfail` 只豁免 XFAIL 条目 |
| 3 | release 记录**强制 hex 哈希**，不可静默落档 | 9594dbb | 审计 M2 已修，勿再报 |
| 4 | verify.py 失败路径退出码非零 | ad9c625 | 双向真机验证过 |
| 5 | 加载器四类缺陷已前置拦截（cg+texts 组合/非法正则/坏 JSON/NaN 边界） | 9594dbb | 审计 M1 已修，同类新发现仍欢迎 |
| 6 | fresh-checker 无上下文自审计已两轮（1H+5M+4L 闭环） | 5ffeb3a、d2c572a | 同源盲区已尽力排除——这正是请你来的原因 |
| 7 | Keil 退役、GCC 为默认唯一 AI 链路 | 1e34524、6405b39 | `scripts/legacy/keil/` 留门区勿动 |
| 8 | **有意搁置**：UART 串口补发布门禁脆弱性 | 主控评估记录 2026-08-27 | 严重度中低+成本高=不立项，报"你怎么不修 UART"属已知取舍 |
| 9 | **有意搁置**：CMSIS 四份 Drivers 瘦身 | 待用户拍板 | 51M/份死重是已知现状 |

## 3. 代管期任务（你的考卷）

**巡检清单四级**（findings 报告按此分节；每级至少"查了+结论"，"无发现"也是结论）：

1. **代码级**（scripts/ 逐文件）：subprocess 超时与返回码纪律 · cwd 依赖（脚本从错误目录跑会怎样）·
   编码（Windows GBK 控制台 / UTF-8 文件读写显式 encoding）· JSON 加载器容错（学 M1 的四连坑思路）·
   try/finally 完整性（feedback 落账路径）· 裸 except 吞错
2. **机制级**：verify.py `--gate-run`/`--rebuild` 有无旁路 · release.py G0-G3 可不可绕 ·
   xfail 翻转逻辑完备性 · feedback_db 落账在哪些失败模式会**静默跳过**（历史上发生过）·
   门禁产物（releases/*.json）可不可被伪造
3. **文档级**：README/注释承诺 vs 代码实际行为（漂移）· blink 退役与 Keil 退役后的失效引用 ·
   `docs/superpowers/` 档案与现状矛盾处
4. **系统级**（⚠️ 只进建议单，不许动代码）：四个全局 skill 的职责重叠/缺口 ·
   toolkit `skills/fresh-checker/` 与全局那份是否漂移（本应同步）· 两工程 `.workbench/`
   契约格式兼容性 · hooks 铁律有无绕过路径

**交付三档**：
- ① **分级发现报告**：本分支 `docs/handoff/<YYYY-MM-DD>-findings.md`。每条：编号 F-00N +
  严重度 + `文件:行号` + **复现法**（命令/输入 → 实际 vs 期望）+ 建议。
  严重度：Critical=静默给错误结果/丢数据 · High=功能错/卡死 · Medium=健壮性/边界 · Low=措辞/漂移。
- ② **直接修**（仅 Critical/High 且改动可在本仓沙盒内完成）：见 §5 commit 纪律，**修复必带回归测试**。
- ③ **建议单**：非可写域的发现一律进 `docs/handoff/<日期>-advice.md`，写明位置与理由。

## 4. 环境接入

- 测试（你的自检与验收都靠它）：在本仓根目录跑
  `python -m unittest discover -s tests` → **当前基线 47 绿**。
- 编译验证（无害，产物不上板）：`python -m unittest` 之外，可用
  `python scripts/gcc_build.py` 相关路径见工程 `.workbench/config.json`（只读）。
- 工具链绝对路径**唯一来源 = `machine.json`**（只读！arm-gcc/make/openocd 位置都在里面）。
- **硬件禁线（机器强制，`scripts/handoff_guard.py` 在换回时扫描你的分支）**：

| 级别 | 禁什么 | 后果 |
|---|---|---|
| L1 文件禁线 | 改 `machine.json`、`hooks/`、`handoff_guard.py` 自身 | 阻断合入 |
| L2 硬件模式（**新增行**出现即查） | openocd 调用（含 -f/--command/flash/verify/init/target remote/resume/halt 语境）、烧录命令（flash write_image / protect / mass_erase / program .hex verify）、串口打开（serial.Serial / import serial / COM口）、RTT 端口 19021、gdb 连硬件（target remote / gdbserver） | 阻断合入* |
| L3 警告 | 改 `verify.py`/`scripts/release.py` 却无 `tests/` 伴随改动 | 不阻断，进人审清单 |

\* 降级规则（内容导向防误杀）：同一模式在**基础版本该文件里已存在**（即你只是在维护既有
硬件层脚本，如 openocd_itm.py），降级为警告但仍进人审清单；tests/ 与 fixtures/ 目录及 .md 等
prose 文件豁免。被 guard 误杀可在日志提异议，主控仲裁后进 allowlist。

**红线**：不接板子、不跑 `verify.py` 的真机段/烧录段、不开串口、不打 tag、不发版、
不 push master。发现"必须真机才能验"的修复——写进 findings 标注"待真机终判"，合入由用户插板验证。

## 5. 交接规矩（开工前必读）

1. 上岗第一步（onboarding 自检，贴给用户/留在日志）：跑 47 套件，确认绿。
2. 工作分支：**`handoff/<你的名字>-<YYYYMMDD>`**。若主控已预建并检出（看 `git branch --show-current`）
   就直接用，**不要再 `-b`**；没有则自行 `git checkout -b`。一切 commit 只落这里；
   master 不属于你。允许 push 分支到 origin（备份），禁止碰 origin/master。
3. commit 纪律：每个发现（组）一个 commit，message 格式 `fix(handoff): F-003 一句话`；
   修复类 commit **必须同时改/加 `tests/` 用例**；文档类 `docs(handoff): …`、发现报告 `chore(handoff): …`。
4. 禁止：顺手重构、批量改名/格式化、调整与本发现无关的代码（一次改动=一个可辩护的理由）。
5. 每日收工在本文末尾「代管日志」**追加**一条：`### YYYY-MM-DD` + 做了什么/下一步/卡点。
   只追加，不重写别人的条目。
6. 发现主控的"勿重做清单"（§2）与现状矛盾——不要按 §2 说的做，把矛盾记进日志（这可能是最有价值的发现）。

## 6. 换回协议（给主控 Claude，用户说"换回来"时执行）

1. **越域核查**：两工程 `git status` 必须干净；`C:\Users\<用户名>\.claude\skills\` 与 `<工作区根>\.claude\`
   下文件 mtime 晚于本文「上岗时间戳」→ 即越域，列为事故先停下。
2. `python scripts/handoff_guard.py --repo . --branch handoff/<x> --json` → blocked 非空则逐条处置
   （误杀→修 allowlist 并补进 test_handoff_guard.py）。
3. `python -m unittest discover -s tests` 全绿 + 抽查编译。
4. 逐 commit **RECONCILE**（审者输出是数据不是裁决）：契约误读 / 有效可行动 / 有效权衡 / 噪声 四分类；
   有争议的记入日志，勿盲从"上下文新鲜"。
5. merge → 请用户插板跑一次 `python scripts/verify.py --json`（adc-oled）真机终判 →
   落账：feedback_db 记 handoff 事件、记忆回填、本文状态行翻转、上岗时间戳更新为下次。

## 双验收（本轮代管成功判据）

①机制跑通：仅凭本文完成 onboarding、提交全在 handoff 分支、guard 绿、日志连续 ≥2 天
②审计有货：findings 覆盖 §3 四级、Critical/High 有复现法、修复带回归测试

---

## 代管日志

（代管者在此追加，格式见 §5 第 5 条）

### 2026-08-30（Day 1，Z code）

- **做了什么**：onboarding 三步全过（47 tests OK、分支 `handoff/zcode-20260830` 确认）；
  §3 四级巡检完成——代码级（核心门禁链 verify/gcc_build/release/feedback_db/wb_runtime/
  hardfault 逐行，其余 20+ 脚本模式级批量扫描+抽查）、机制级（G0-G3 绕过面/gate-run 旁路面/
  releases 伪造面/§2 清单对照）、文档级（README/AGENTS/HANDOFF 无漂移，blink 残留 3 处）、
  系统级（三 skill 根比对+两工程契约核查，全部只读）。
- **产出**：`docs/handoff/2026-08-30-findings.md`（F-001~F-013 + M-1~M-4 + D-1~D-2）、
  `docs/handoff/2026-08-30-advice.md`（A-01~A-05）。
- **修复**：F-001（Critical）feedback_db 首次落账死锁——工程根存在但 feedback 目录不存在时
  误报"未找到工程根"exit 1，verify 侧静默吞掉 → button-toggle 现役工程建成以来反馈零落账。
  修复+4 例回归（`tests/test_feedback_db.py`），套件 51/51 绿，commit 4866fb5。
- **关键结论**：§2 勿重做清单 8 个证据 commit 全部在案，**与现状无矛盾**；G0-G3 与
  gate-run/rebuild 无旁路；fresh-checker 双份与 .zcode/.claude 双 skill 目录均无漂移。
  Medium 未修项（F-002 config 容错 / F-003 采集超时丢输出 / F-004 落账无痕 / F-005
  hardfault map 失效）按 §3 纪律留主控拍板，F-003/F-005 已标注**待真机终判**。
- **下一步**：Day 2 拟深查 release G1 的 expectations 时序窗口（G0 clean 与 G1 重跑之间
  config/expectations 的语义一致性）、gcc_build state.json 写入竞态、gen_periph/svd_to_json
  逐行补扫、serial_mux（514 行）未细读部分。
- **卡点**：无。guard 自查 clean（0 blocked / 0 warnings）。
