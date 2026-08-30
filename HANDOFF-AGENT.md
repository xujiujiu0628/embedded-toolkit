# 交接文档：embedded-toolkit → 外部智能体代管期

> **本文读者**：被用户请来独立检查/改进本工作台的智能体（如 Z code）。你没参与过它的演进——
> 本文是你的唯一上手材料，读完 §1-§5 即可开工。**主控（Claude Code）代管期不介入**，换回见 §6。
> **第二轮上岗时间戳**：____（主控发车前填；§6 越域核查以此为界）｜第二轮分支：`handoff/zcode-r2-<YYYYMMDD>`
> **状态**：首轮（Z code，08-30，`handoff/zcode-20260830`）已全案闭环——双验收✅ + 插板终判四项真机全绿 +
> F-015/016/017 主控当日补修 + A-02 对账完成（findings 末尾）。本文件现为**第二轮考卷**（§3 有专项题）。
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

本仓内部：`scripts/`（29 个脚本，入口 verify.py，默认 builder=gcc；首轮新增 handoff_guard/release_audit）、
`tests/`（**106 测试**，python -m unittest）、`data/`（stm32f103-ref.json 55 外设 + 错误库）、`hooks/`（3 条 C 代码铁律检查）、
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
| 10 | 首轮遗留 F-015/F-016/F-017 **均已修** | 920e187(F-005 三层) / 1819e18(F-015/16/17) | duration_sec 已进 toggle 契约=90；勿报"仍未修" |
| 11 | `.agents/skills` 已刷到 7-skill 终态（A-02 兑现） | f4b5d4f 对账记录（哈希+CreationTime 举证） | 勿凭 mtime 判"没发生"——copy2 保源时间戳；`.zcode` 根措辞对齐(A-03)属主控侧遗留，非本仓缺陷 |

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

**第二轮专项题（用户钦定 A/B/C/D 全包；通用四级仍要"查了+结论"，但完成度按专项题验收）**：

- **A · 首轮你自己没做完的调查**：
  A1 release G1 的 expectations 时序窗口——G0 clean 判定与 G1 重跑之间替换/改坏
  expectations.json，能否骗过门禁或制造假绿？给出复现（脚本/测试）或证明不可达。
  A2 gcc_build `state.json` 写入竞态——双进程并发 build 同一工程：update_state_entry
  读-改-写是否丢更新/写坏 JSON？结论 + 若真实则修复（原子写/加锁，带回归）。
- **B · 写回型工具专项（F-017 同族扫描）**：全仓找"默认参数路径会写回配置/状态"的点
  （save_project_config / update_state_entry / error_db_grow / load_project_config 各默认
  段名用法…），逐个核：默认参数被触发时会写坏什么？每个写回点补**默认路径回归测试**
  （首轮教训：verify 总显式传参所以主干无恙，手工路径一测就中）。
- **C · 测试覆盖率推进**：`python -m coverage`（如缺则 unittest 手工圈定）找出零覆盖模块
  （serial_*/openocd_* 后端/gen_periph/rm_lookup/token_stats 等），纯 mock 补回归，
  **不得触硬件**；每模块提交前说明它真实消费方是谁（防为死代码造测试）。
- **D · 文档对齐 + 小工具**：
  D1 README/HANDOFF/AGENTS 数字与现状对齐（106 基线、29 脚本、release_audit 入 §1 地图）
  D2 toolkit VERSION 0.1→0.2 + CHANGELOG.md 从 git 历史生成（条目须能对到 commit，防吹）
  D3 新工具 `scripts/expectations_lint.py`：提交前静态校验 expectations.json（id 唯一/
  texts+patterns 并存/缺 xfail_reason/pattern 可编译性——对齐 9594dbb 加载器的运行期规则，
  把"烧录后才炸"提前到"git add 前就能抓"）；带正反例测试。
- **判据方法论（首轮三例教训，本轮巡检必须照此办事）**：内容导向——版式类判据拿真档冒烟
  （F-005）；复制/镜像类操作用 CreationTime+哈希取证而非 mtime（A-02 对账）；写回类默认
  路径必须有测试（F-017）。

**交付三档**：
- ① **分级发现报告**：本分支 `docs/handoff/<YYYY-MM-DD>-findings.md`。每条：编号 F-00N +
  严重度 + `文件:行号` + **复现法**（命令/输入 → 实际 vs 期望）+ 建议。
  严重度：Critical=静默给错误结果/丢数据 · High=功能错/卡死 · Medium=健壮性/边界 · Low=措辞/漂移。
- ② **直接修**（仅 Critical/High 且改动可在本仓沙盒内完成）：见 §5 commit 纪律，**修复必带回归测试**。
- ③ **建议单**：非可写域的发现一律进 `docs/handoff/<日期>-advice.md`，写明位置与理由。

## 4. 环境接入

- 测试（你的自检与验收都靠它）：在本仓根目录跑
  `python -m unittest discover -s tests` → **当前基线 106 绿**（47→89→97→106 为两轮
  修复的正常增长，勿把"测试变多"当漂移发现）。
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

1. 上岗第一步（onboarding 自检，贴给用户/留在日志）：跑 106 套件，确认绿。
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
   （误杀→修 allowlist 并补进 test_handoff_guard.py；程序化消费走 subprocess，勿经 PowerShell
   管道——PS5.1 会注入 BOM）。降级警告项（如硬件层脚本的维护性改动）逐条人审定性。
2.5 `python scripts/release_audit.py --project <工程根> --all` → 发布记录 R1~R6 审计 CLEAN
   （首轮 Z code 贡献的新工具，纳入换回协议）。
3. `python -m unittest discover -s tests` 全绿 + 抽查编译（gcc_build 真编一工程，产物不上板）。
4. 逐 commit **RECONCILE**（审者输出是数据不是裁决）：契约误读 / 有效可行动 / 有效权衡 / 噪声 四分类；
   有争议的记入日志，勿盲从"上下文新鲜"。
5. merge → 请用户插板跑一次 `python scripts/verify.py --json`（adc-oled）真机终判 →
   落账：记忆回填、本文状态行翻转、上岗时间戳更新为下次。
   （协议缺口修正：feedback_db 强依赖工程根，被审对象为 toolkit 本身时无工程可落，
   handoff 事件记于本文「代管日志」即完成落账——勿为走步骤而硬造工程目录。）

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

### 2026-08-30（Day 2，Z code）

- **做了什么**：用户认可"失败路径必须留痕"改进方向并背书后，把 Day 1 定为 Medium 留拍板的
  四项按 §5 纪律（带回归测试）全部修复：
  - **F-004** 落账留痕：verify.py 抽出 `_log_feedback_event`，落账成功/`--gate-run` 跳过/
    失败三态全部写入 `result.feedback`（含 event_id / reason / error），消费方不再无法区分；
    原 `except: pass` 吞掉 feedback_db exit 1 的路径消除。
  - **F-002** config 容错：`load_config` 损坏 JSON/非 UTF-8 抛 `ConfigError`，main 友好退出，
    与 M1 的 ExpectationError 同款模式。
  - **F-003** 超时诚实化：行过滤抽为 `_filter_capture_lines`（正常/超时共用口径），
    OpenOCD 卡死超时走 `_finish_capture_timeout`——回收部分输出进 result 与 last_failure.json，
    顶层判 capture_failed，不再伪装"程序无输出"。**待真机终判**。
  - **F-005** hardfault 默认 map 自动发现（cwd 向上找工程 lst/*.map），blink 残留路径只作
    兜底。**待真机终判**。
- **产出**：2 个 fix commit（1baeed2 / 11eb319）+ 23 例新回归；套件 **70/70 绿**；
  findings.md 状态回填。
- **下一步**：Day 3 拟做收尾：serial_mux/openocd_gdb 等剩余脚本补扫结论、F-006~F-013 Low 项
  的 except 逐条"留痕或注释理由"审计表、findings/advice 终稿、日志收官。
- **卡点**：无。test_verify_failure_paths 运行时 _output 会向 stdout 打印两段 JSON
  （_finish_capture_timeout 的诚实输出路径），unittest 不受影响，属预期行为。

### 2026-08-30（Day 3，Z code，收官）

- **做了什么**：用户授权后完成 Day 3 计划 + 第二层第 1 条：
  - **F-014（新编目，Day 1 复盘漏项）**：feedback_db 校准库损坏裸崩全部落账 →
    修复为"损坏移 .corrupt 保留现场 + 空库重建"（afc7265，4 例回归）；两步写语义
    （事件先落盘、索引后更）以测试固化为可恢复设计；补全空库模板缺 verify/fresh_check
    计数键。
  - **Low 组处置**：F-006/007/008/012 修（fa5efb4，4 例回归），F-009/010/011/013
    记录不修——逐条理由已写入 findings 处置表。
  - **六脚本补扫**（约 3800 行）：深度模式扫描+人工抽查，无新发现；serial_mux 宽
    except 均带正确副作用非吞错（findings §七有结论）。
  - **release_audit.py（新工具，M-3 处置）**：发布记录事后审计 R1~R6（tag↔HEAD、
    hex 重算哈希、results 自洽、结构完整、入库检查），只读不触硬件（eb1e4c9，
    11 例篡改场景回归）；真实冒烟 adc-oled v1.1.0 → **CLEAN**。
  - **插板验证清单**：findings §七给出换回后 5 步终判步骤（覆盖 F-001/004/003/005
    的"待真机终判"项）。
- **产出**：Day 3 共 3 个 commit（afc7265 / fa5efb4 / eb1e4c9）+ findings 终稿 §七；
  套件 **89/89 绿**（47 基线 + 42 新增回归）。
- **三天总账**：发现 F-001~F-014（1 Critical + 5 Medium 修复 + 4 Low 修复 + 4 记录
  有据不修）+ 新工具 1 个 + 机制/文档/系统级结论与建议单；修复类 commit 全部带回归
  测试；F-003/F-005 标待真机终判并给出插板步骤。
- **下一步（换回人审）**：RECONCILE 逐 commit 四分类复核；guard 扫描（本日自查
  clean）；建议把 release_audit 纳入换回协议第 2 步。
- **卡点**：无。工作区干净，未触 master/两工程/硬件。

### 2026-08-30（换回，主控 Claude）

- **§6 五步执行记录**：越域核查✅（master 未动 6608be2、两工程净、skills/<工作区根>\.claude 无新mtime；
  补扫 `.agents` 根亦未改）→ guard clean（10 commit，0 blocked，1 降级警告 verify.py/openocd_call
  定性为 F-003 维护性改动，放行）→ 套件 89/89 + release_audit 两真档 CLEAN → merge --no-ff 5c7515a
  → 本条为落账。
- **RECONCILE 四分类**：有效可行动×8（含 F-001 根因级修复）、有效权衡×4（F-009~013 留痕不修，理由
  成立）、契约误读×0、噪声×0。保留意见 2 条已处置：①F-005 残留半项——主控补丁
  `_map_degradation_note`（空符号表必须告警）+3 例回归；②release_audit 纳入 §6 第 2.5 步。
- **A-02 核实追加**：`.agents/skills` 确为 08-25 大清理**前**的陈旧快照（review-code 仍 ARMCC 口径，
  且含已退役 review-build/keil/openocd/serial 与 doubt-driven 全家）。属越域外遗留，待用户拍板：
  刷新至 6-skill 终态 or 删除退役项。
- **双验收判定：①机制跑通 ✅ ②审计有货 ✅ —— 首轮代管闭环成立。**
- **待办**：F-003/F-005 插板终判（清单见 findings §七）→ 终判绿后 push tag 收口。

### 2026-08-30（插板终判，主控 Claude）

- §7 清单全过：adc-oled verify 全绿+feedback.logged(17:35) → toggle .workbench/feedback
  **历史首建**、四次事件累计 → hardfault 真机 symbols_total 126、PC→HAL_GetTick+2
  （F-005 实为三层洋葱，已于 920e187 全修+5 回归）→ release_audit 两真档 CLEAN。
- FR-KEY-01 第四轮真按键通过（TGL 0001-0070）；前三轮败于 --timeout 10s 默认窗——
  编目 F-016。**首轮代管全案终判：通过。**

### 2026-08-30（主控补录，F-015/016/017）

- 不等第二轮：当日修 F-015（workspace 跟随 --project）+ F-016（采集窗进契约，
  toggle duration_sec=90，stderr 预告窗口）；E2E 事故重放衍生发现并修复 **F-017**
  （load_project_config 段语义双重错误——不传 --target 的手工 gcc_build 会写坏工程 config）。
- 106/106 全绿；toggle 契约 diff 仅 duration_sec 一处（target 已复原）。
- 教训：写回型配置工具的**默认参数路径**必须被测试覆盖——verify 一直显式传参所以
  主干无恙，手工路径从没测过，一测就中。
