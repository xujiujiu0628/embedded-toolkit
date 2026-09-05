# Changelog

格式约定: 每条含发现编号（代管期 findings 编目）与证据 commit。当前版本以
`VERSION` 文件为准（`wb_common.toolkit_version()` 读取）。

## Unreleased — 2026-09-05（0.4 复核收口：账目 hash / 索引兜底 / 语法卫生，F-051~053）

- **F-051 处置（0.4 账目证据 hash 断链，docs）**: 0.4 节 F-047 引用的 `6e3ebbc` 是
  署名重写前短 hash（重写后现行历史为 `eef1851`）——0.3 重写曾声明"重写前短 hash
  全部失效"，本次重写漏做等效声明。外部复核逐 hash 验证 0.4 节 16 个引用：15 OK
  / 1 MISS，本条即该 MISS。处置=账目改指现行 hash。教训=历史重写后必须重跑
  CHANGELOG 引用 hash 全量可解析性检查（`git rev-parse --verify <hash>^{commit}`）。
- **F-052 处置（.workbench 运行时产物无索引兜底，chore）**: F-047 新增
  checkpoints.jsonl 与既有 state.json / *.corrupt 均写入固件工程 `.workbench/`，
  而本仓 .gitignore 无该条目——F-015 伪工程事故路径若在仓内复现，台账产物将进入
  git status 并有误提交风险（实测 check-ignore 未命中）。处置=.gitignore 增
  `.workbench/`；固件工程侧"config/expectations/releases 入库、state 忽略"的建议
  不变（见 README）。
- **F-053 处置（tests docstring 非法转义 SyntaxWarning，fix+test）**:
  test_failure_hints.py:3 非原始 docstring 含 `\.`——Python 3.12+ 升格为
  SyntaxWarning，coverage_lint 的 AST 全扫每轮都向 stderr 吐警告。处置=docstring
  改 raw；新增 test_source_hygiene 钉：scripts/ + tests/ 全量逐文件 compile，
  SyntaxWarning 与 DeprecationWarning（3.10/3.11 上同类告警的旧名）均升格 error
  防回潮。外部复核时扫描全仓仅此 1 处。
- **F-054 处置（verify/hardfault 模块级副作用惰性化，refactor，防腐方案 §3.3 步骤 1）**:
  两脚本曾有模块级 `OPENOCD_EXE = load_machine()[...]`——import 即文件 IO，
  machine.json 缺失时向 stderr 吐回退警告，6 个测试文件被迫注释豁免，CONTRIBUTING
  禁令 #2 亦以此为存在理由之一。处置=verify 改 `_openocd_exe()` 惰性函数（4 个使用点
  同步替换），hardfault 在 run_openocd_diag() 内惰性解析；新增 test_import_hygiene
  钉（fresh-import 式绕过 sys.modules 缓存：load_machine spy 断言 import 期零调用 +
  stderr 零输出 + 常量不再绑定）；6 例测试豁免注释收编；CONTRIBUTING 禁令 #2 /
  AGENTS.md 速查同步改写——禁令保留，理由从"副作用"升级为"分层"，防回潮机制不变。
  先红后绿：钉在修前 3/3 红（spy 命中），修后 3/3 绿。这是 verify.py 拆解
  （防腐方案 §3.3）的前置步骤——此后拆出的模块不再背负 import 期 IO。
  全量 **306 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-055 处置（expectations.py 拆分件——verify.py 拆解步骤 2，refactor，防腐方案 §3.3）**:
  期望契约层自 verify.py 摘出成 `scripts/expectations.py`（166 行）：ExpectationError /
  load_expectations / evaluate_expectations / _expect_matched / contract_hashes（含仅其
  使用的 _sha256_file）五符号整体搬迁，全部本就带 workspace 参数、零全局依赖，纯函数
  可单测。wire 兼容=verify 再导出五符号（`verify.X is expectations.X` 同一对象实测），
  35 处 `verify.X` 测试引用零修改；`import math` 随唯一使用点迁出。新模块仅标准库、
  不 import verify（分层禁令 #2）、无 machine 读取（test_import_hygiene 经 import 链
  继续覆盖）。钉=既有 24 例判定 + fixture 三关 + 35 处调用面，钉全程保持全绿；
  verify.py 1832 行（F-050 时长画像显示 capture 占 67%，下一步步骤 3 摘 capture_rtt）。
  本条纯搬迁零新增用例，全量 **306 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-056 处置（capture_rtt.py 拆分件——verify.py 拆解步骤 3，refactor+test，防腐方案 §3.3）**:
  RTT 采集后端整体摘出成 scripts/capture_rtt.py（204 行）：_step_capture_rtt（更名公开
  step_capture_rtt）+ _rtt_telnet / _rtt_read_until_prompt / _rtt_cleanup + 两个 _RTT_*
  常量。行为逐字节不变的两组差异：① WORKSPACE 全局改 workspace 参数（verify 调度点
  传参，OpenOCD 子进程 cwd 语义不变）；② openocd 路径经 load_machine 惰性解析
  （F-054 惯例）。wire 兼容 = verify `from capture_rtt import step_capture_rtt as
  _step_capture_rtt` 再导出旧私有名——3 处测试钉零修改：2 处
  mock.patch.object(verify, "_step_capture_rtt")（return_value 型 mock 任意签名兼容，
  调度点加传 workspace 不破）+ F-031 运行时钉（patch 的是 sys/subprocess/time 共享
  模块对象，对本模块同样生效）。verify.py 1646 行（-187），socket/threading import
  随唯一使用点迁出。**红利**：新增 test_capture_rtt 七例——RTT 时序（reset halt →
  resume → 宽限 → rtt setup → rtt start → server start 逐条断言，F-003 级防假 PASS
  知识）拆分前从未被真断言，现为真单测；另钉控制块未找到不重试、3 次竞态重试、
  存活会话 halt+shutdown 礼貌清理、_rtt_read_until_prompt 三态、2 参旧调用形态兼容。
  全量 **313 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-057 处置（physical_gate.py 拆分件——verify.py 拆解步骤 4，refactor+test，防腐方案 §3.3）**:
  物理层门控整体摘出成 scripts/physical_gate.py（188 行）：step_physical_gate 同名搬迁
  （TCL 运行时生成 + PHYS_GATE_RESULT 解析 + 判定数学 + 各 probe_error 分支）。
  差异三点（逐字节搬迁前提下）：WORKSPACE 全局改 workspace 参数（TCL 落盘与子进程
  cwd 均用之）；openocd 路径经 load_machine 惰性解析（F-054 惯例）；函数内
  `import re as _re` 原样保留。wire 兼容 = verify 同名再导出，调度点加传 workspace；
  无测试直接引用该符号，签名扩展零破绽。verify.py 1482 行（-164），datetime 等
  其余 import 仍被 verify 其余部分使用故保留。**红利**：新增 test_physical_gate
  八例——TCL 生成逐片段钉（预热节奏注释/初始化边沿告警/read_memory/mask 插值/
  结果行格式）、判定数学（4.0/s ok、4.8/s timing_fail+时钟树回滚文案）、
  insufficient_samples、三类 probe_error、禁用态零开销守卫。修前这些逻辑
  需要真机才能走到，从未被断言过。全量 **321 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-058 处置（doctor.py 拆分件——verify.py 拆解步骤 5a，refactor，防腐方案 §3.3）**:
  环境预检家族整体摘出成 scripts/doctor.py（279 行）：doctor_report / _print_doctor /
  _check_tool / _first_version_line / _detect_default_branch / _fixture_main_sha /
  fixture_health / _DOCTOR_KEYS 整块逐字搬迁（F-041 引入的原块）。差异仅 import
  收归本模块（os/subprocess/sys/hashlib + openocd_runtime.swd_probe + wb_common 四件），
  抽取脚本断言块内零 WORKSPACE 引用（F-041 的 workspace 无关设计在此兑现）。
  wire 兼容 = verify 再导出五符号（doctor_report/fixture_health/_print_doctor/
  _detect_default_branch/_fixture_main_sha），调度分支与 CLI 零改动。测试 patch 目标
  随迁（F-029 先例）：test_doctor 三处 load_machine、test_fixture_doctor 一处
  _fixture_main_sha 改钉 doctor 模块；subprocess.run 为共享模块对象原钉不动。
  经验入账：逐字搬迁块必须跑 AST 未定义名扫描——首轮漏 TOOLKIT_ROOT/hashlib/sys/
  swd_probe 四个 import，靠 import 报错逐个补不如一次性静态扫。
  verify.py 1482 → **1225 行**。全量 **321 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-059 处置（checkpoint_ledger.py 拆分件——verify.py 拆解步骤 5b，refactor，防腐方案 §3.3）**:
  F-047 台账家族摘出成 scripts/checkpoint_ledger.py（120 行）：CHECKPOINT_STATUSES /
  _git_head / record_checkpoint（双写逻辑）逐字搬迁；**_record_checkpoint_early_exit
  留守 verify**——它是读 WORKSPACE 全局与 result/args 的编排胶水，留守使其对
  record_checkpoint 的调用仍走 verify 再导出面，test_build_failed_records_checkpoint
  的 patch 零修改。wire 兼容 = verify 再导出三符号，main() 调度、早退 5 调用点、
  10 处测试调用零修改。测试 patch 目标随迁：test_checkpoint_ledger 10 处
  `_git_head` 改钉 checkpoint_ledger 模块（record_checkpoint 内部解析已随迁，
  verify 层 patch 不再可拦截——F-029 先例）。`atomic_write_json` 随唯一使用点
  迁出 verify 的 import。已知语义微调（记账）：ts 由 verify 本地 now_iso（固定
  +08:00）改为 runtime_common.now_iso 规范版（本地时区）——时刻不变，本机
  +08:00 输出逐字节一致。verify.py 1225 → **1129 行**。
  全量 **321 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-060 处置（failure_context.py 拆分件——verify.py 拆解步骤 5c，refactor，防腐方案 §3.3）**:
  失败现场家族摘出成 scripts/failure_context.py（156 行）：_save_failure_context
  （agent_hint 五分支派发）/ _filter_capture_lines（F-003 行过滤口径）+ 两常量 /
  resolve_capture_timeout（F-016）。**_finish_capture_timeout 留守 verify**——内嵌
  sys.exit(1) 与 _output 调用，是派发胶水而非逻辑；经再导出面调用本模块。
  差异三点（记账）：WORKSPACE 全局改 workspace 参数（verify 7 处调用点同步传参）；
  TOOLKIT_ROOT 自 wb_common 导入（agent_hint 随其推导，test_failure_hints 钉改指
  failure_context 模块）；ts 走 runtime_common.now_iso（同 F-059 记账）。
  静态守卫跟进：test_failure_hints 的维护者路径扫描增加 failure_context.py——
  提示串搬去哪，守卫跟到哪。经验复用：抽取后立即 AST 未定义名扫描（F-058 教训
  兑现，本次零缺失）。verify.py 1129 → **993 行**（跌破千行）。
  全量 **322 全绿**（+1=守卫新增 failure_context.py 扫描例；skipped=1 仍 F-026）。
- **F-061 处置（capture_semihosting.py 拆分件——verify.py 拆解步骤 5d 收官，refactor+test，防腐方案 §3.3）**:
  main 内联 semihosting 会话摘出成 scripts/capture_semihosting.py（64 行）：
  run_semihosting_session（cmd 构建/Popen/communicate）+ SemihostingTimeout 载体异常。
  **控制流契约（关键设计）**：超时 → 抛 SemihostingTimeout(proc) 且**模块不 kill
  不收尸**——F-003 的回收/归因/exit(1) 全在留守的 _finish_capture_timeout（携带
  proc 完成），归因链逐字节不变；非超时异常原样抛出由调用方 capture_failed 分支
  处理（与原行为一致）。调度点注释（reset halt 确定性起点/2026-08-16 教训/F-028
  留门）原位保留。verify.py 993 → **977 行**。**红利**：test_capture_semihosting
  三例——cmd 逐条钉（含 sleep ms 换算与 cwd）、超时载体不抢先 kill（防二次回收
  拿不到部分输出的回归）、非超时异常透传。逻辑全部外置达成：verify.py 剩余 =
  编排调度 + 报告输出（纯胶水，F-049 行数哲学：不再为凑 300 行而碎片化）。
  全量 **325 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-062 登记+处置（推送权限纪律缺位，docs，维护者拍板）**: 维护者 2026-09-05
  明确要求：Agent 不得直接 push 远端，推送须先经维护者审核——此前 Agent 具备
  push 能力且无成文约束（当前 15+ 提交未推送即为待审状态）。处置=CONTRIBUTING
  增「推送纪律」节 + AGENTS.md 速查补行：本地 commit → 维护者审核 → 维护者推送
  或明确授权；推送前检查清单（全量测试绿 / 工作区干净 / CHANGELOG 引用 hash
  可解析——历史重写后尤甚，见 F-051）；force-push 仅限维护者执行。纯文档零代码。

## Unreleased — 2026-09-05（防腐方案 §3.3 拆解 7 模块收官 + 推送纪律成文 + 仓边界清理 + 修复收口）

15 commit 累计，含 14 commit 已推 GitHub master（`96796ed..60d9bc0`）+ 1 commit
本地领先（`dc94b12` 仓边界清理，待推）：

- **F-054 处置（拆解前置：OPENOCD_EXE 模块级惰性化，refactor）**:
  `scripts/verify.py` `scripts/hardfault.py` 曾有模块级 `OPENOCD_EXE =
  load_machine()[...]`——import 期即文件 IO + stderr 回退警告，6 个测试文件被迫
  注释豁免。常量改 `_openocd_exe()` 惰性函数，4 个使用点同步替换；新增
  `test_import_hygiene` 钉（fresh-import spy + stderr 零输出 + 常量不再绑定，
  先红后绿）；6 例测试豁免注释收编；CONTRIBUTING 禁令 #2 理由升级为"分层"
  （verify 是 Layer 2 编排主体，防回潮机制不变）。verify.py 1832 行起点。
  全量 306 全绿。
- **F-055 处置（拆解步骤 2：expectations.py 拆分件，refactor）**: 期望契约层
  5 符号摘出（166 行，零全局依赖、纯函数可单测）；verify 再导出 5 符号，35
  处测试零修改（F-029 同款手法）；分层禁令 #2 兑现（新模块不 import verify /
  无 machine 读取）。verify.py -154 行。全量 306 全绿。
- **F-056 处置（拆解步骤 3：capture_rtt.py 拆分件，refactor）**: RTT 采集后端
  4 符号摘出（204 行，行为逐字节不变）；`WORKSPACE` 全局改 `workspace` 参数，
  OpenOCD 子进程 cwd 语义不变；2 参旧调用形态经缺省值 None 保持兼容
  （`test_capture_rtt` 钉）。verify.py -187 行。新增 7 例真单测——RTT 时序
  钉死 F-003 级防假 PASS（reset halt → resume → 宽限 → rtt setup → rtt start
  → server start 逐条断言）、控制块未找到不重试、3 次竞态重试、存活会话
  halt+shutdown 礼貌清理、2 参旧调用形态兼容。verify.py 1646 行。全量 313 全绿。
- **F-057 处置（拆解步骤 4：physical_gate.py 拆分件，refactor）**: 物理层门控
  整体摘出（188 行，WORKSPACE 全局改 workspace 参数 + openocd 路径惰性解析）；
  新增 8 例真单测——TCL 生成逐片段钉（预热节奏注释 / 初始化边沿告警 /
  read_memory / mask 十进制插值 / 结果行格式）、判定数学（4.0/s ok、4.8/s
  timing_fail + 时钟树回滚文案）、三类 probe_error 路径（无稳态闪烁 / 读失败
  率超限 / 无结果行 3 重试）、禁用态零开销守卫。verify.py -164 行。
  全量 321 全绿。
- **F-058 处置（拆解步骤 5a：doctor.py 拆分件，refactor）**: 环境预检家族整体
  摘出（279 行，零 WORKSPACE 引用——F-041 的 workspace 无关设计兑现）；verify
  再导出 5 符号，调度分支与 CLI 零改动；经验入账：首轮漏 4 个 import（hashlib/
  os/subprocess/sys + swd_probe + wb_common），靠 import 报错逐个补；教训
  复用：抽离后立即 AST 未定义名扫描。verify.py -261 行。全量 321 全绿。
- **F-059 处置（拆解步骤 5b：checkpoint_ledger.py 拆分件，refactor）**: F-047
  台账家族 4 符号摘出（120 行）；`_record_checkpoint_early_exit` 留守 verify
  （读 WORKSPACE 全局与 result/args 的编排胶水）；wire 兼容 = verify 再导出
  3 符号，10 处测试 patch 目标随迁（F-029 先例）；ts 走 `runtime_common.now_iso`
  规范版（时刻不变）。verify.py -96 行。全量 321 全绿。
- **F-060 处置（拆解步骤 5c：failure_context.py 拆分件，refactor）**: 失败现场
  家族 4 符号摘出（156 行）；`_finish_capture_timeout` 留守 verify（嵌入
  sys.exit(1) 与 _output 调用——派发胶水而非逻辑）；WORKSPACE 全局改
  workspace 参数（7 处同步）；TOOLKIT_ROOT 自 wb_common 导入——agent_hint
  指引随其推导；ts 走 runtime_common.now_iso。verify.py -136 行。
  全量 322 全绿。
- **F-061 处置（拆解步骤 5d 收官：capture_semihosting.py 拆分件，refactor）**:
  semihosting 会话 2 符号摘出（64 行）；控制流契约（成功 → 返回 tuple；
  超时 → raise `SemihostingTimeout` 携带 proc，模块不 kill 不收尸——F-003 的
  回收/归因/exit(1) 全在 `_finish_capture_timeout` 留守）；非超时异常原样
  抛出。verify.py -16 行（终点 977 行）。新增 3 例真单测（cmd 逐条钉、超时
  载体不抢先 kill、非超时异常透传）。全量 325 全绿。**防腐方案 §3.3 拆解
  收官**——verify.py 剩余 = 编排调度 + 报告输出（纯胶水）。
- **F-062 处置（推送权限纪律成文，docs）**: CONTRIBUTING 增「推送纪律」节 +
  AGENTS.md 速查补行（同节首见"治理史→本文件"归属说明）；推进动机：维护者
  无 push 能力且无成文约束（当前 15+ 提交未推送即为待审状态）。处置=本地
  commit → 维护者审核 → 维护者推送或明确授权；推送前检查清单（全量测试绿 /
  工作区干净 / CHANGELOG 引用 hash 可解析——历史重写后尤甚，见 F-051）；
  force-push 仅限维护者执行。**纯文档零代码**。
- **F-051~053 修复收口（fresh-checker 复核 High 处置 9-05 上午）**:
  - **F-063（H3 修复，code）**: `physical_gate.py` `fail_reads` 解析改
    默认 -1 + ValueError 异常 + 负值 raise `probe_error`——
    修前非法值（`abc` / 负号 / 缺失）静默默认 0 绕开"读失败率超限"分支；
    修后探针实测 `fail_reads=abc` → status=probe_error。3 例新 test 钉
    （缺失/负值/字母三路径）。全量 327 全绿。`71fb20a`。
  - **F-064（H2 修复，docs）**: CHANGELOG 0.4 节标题下补"本账目与 docs 中
    引用的'重写前短 hash 全部失效'——同 0.3 节 9-01 公开准备的声明"等效
    段，覆盖两轮重写（0.3 filter-repo 脱敏 + 9-02 推送署名 filter-branch
    user-identity）；引用本节 hash 前请用
    `git rev-parse --verify <hash>^{commit}` 验证现行可解析。`c3bcb6d`。
  - **F-065（H1 标注，docs）**: F-062 推送纪律节末尾 + AGENTS.md 速查同位
    追加"本节性质"段，显式标"道德约束非技术卡"——本仓无任何 git hook /
    pre-push / CI 阻断逻辑会拦截 Agent 推送，技术兜底在（1）GitHub 远端
    分支保护 master 需 PR + ≥1 审 +（2）维护者人工审核；防"以为已卡死"
    误读。`60d9bc0`。
- **`19c9521 chore(setup-matt-pocock-skills)` 处置（agent 协作 skill 落地,
  docs）**: 19 个 PR 待审期间按 Matt Pocock skills 框架注册工程——docs/agents/
  三件套（issue-tracker / triage-labels / domain）+ AGENTS.md ## Agent skills
  段指向上述文件；本次"AI 协作私约"迁出后该 commit 的 docs/agents/ 实际
  已不在仓内（`dc94b12` 边界清理合并删除），但其本意"工作流登记"以新仓
  `D:\claude\embedded-handoff\docs\agents\` 形式继续存在——按维护者
  拍板，登记本节作为完整性记账。
- **`dc94b12` 仓边界清理（refactor 0.4 边界）**: 维护者拍板公开工具库
  embedded-toolkit 不应含维护者 ↔ Agent 协作私约——迁出 17 文件（AGENTS.md
  / HANDOFF-AGENT.md / docs/agents/×3 / docs/handoff/×5 / docs/superpowers/×6
  / skills/fresh-checker/×1）到新私有仓 `D:\claude\embedded-handoff\`
  （独立 git 仓，commit `0845ea6`，不推 GitHub 远端）；本仓改写 3 文件
  （CONTRIBUTING 删"推送纪律"段 + README 结构图/文档索引/末段去私约引用 +
  handoff_guard.py docstring 引用改外链 + raw string 修正 SyntaxWarning
  复用 F-053 教训）；**本仓净减 3511 行**。scripts/handoff_guard.py
  保留——沙盒禁线机器判据是工具库本职而非私约，spec 文档迁出后由维护者
  人工外链引用。

## 0.4 — 2026-09-04（质量守门 + 契约统一）

> **本账目与 docs 中引用的"重写前短 hash 全部失效"**——同 0.3 节"开源准备"
> （line 472~480）的声明。本节内容经两轮重写：① 0.3 公开准备 filter-repo
> （脱敏 Windows 用户名+工作区盘符），重写前 commit 图封存于
> `../archive/embedded-toolkit-prehistory-20260901.bundle`；② 0.4 复核前
> 9-02 推送署名 filter-branch（xujiujiu0628 user-identity filter-branch），
> 详见 [[push-user-identity-rule]]。引用本节 hash 前请用
> `git rev-parse --verify <hash>^{commit}` 验证现行可解析；现行 0.4 节
> 16 hash 引用经 F-051 复核 16/16 可解析。

本版主题：**五条守门工具齐备 + runtime_common 共享层抽取 + HIL 入口可追溯**。
50+ commit 兑现路线图 F-035~050 全链 + F-029 整车收口；F-号账目分散于下方
6 段 Unreleased 按发现日期归档（回放粒度优先于合并重排），本节只做导览。

### 五条守门工具

- **HIL 入口可追溯（F-046）**：`release.py gate1` 启用 schedule origin 守卫
  （`--require-schedule-origin`），flash / capture 必经台账。`6561e31`
- **verify 进度台账（F-047）**：checkpoints.jsonl + state.json 双写，早退
  路径不落账 + 落盘扩 step_durations + atomic_write_json 防撕裂。
  `eef1851 / e5852e3 / f850154`
- **fixture doctor（F-048）**：doctor 体检新增 fixture_health 三态判定
  （在场 / 漂移 / 正常），git show main 对比不污染工作树。
  `1231bb6 / 4dad1b2`
- **scripts/ 覆盖缺口 lint（F-049）**：AST 扫 test_*.py import 找未被引用
  scripts 文件，取代行数红线。`c7e2a48 / 7da9b27`
- **分层前时长画像（F-050）**：verify step-level timing 埋点（build /
  flash / capture / rtt 都有 duration_sec） + duration_profile 工具出
  min/p50/p95/max/占比。`35bef57 / c4487b7 / 23103b3`

### 契约统一

- **F-029 runtime_common 共享层**：wb / openocd / serial 三 runtime 22
  个同名符号抽取到 Layer 0.5 共享层（25 规范符号防环），AST 同形重复
  浪费 **195→4 行**；17 工具消费方零迁移，特征钉先按现实绿（`serialize`
  hook 注入保三家分叉、`normalize_path` serial 留份、`save_local_config`
  守卫撤销——整写天然免损）。`17b58f3 / 7b81786 / 98a36f9 / 6d9a898 / 3c2dba6`

### 防腐纪律 + 文档统一

- **F-035** CONTRIBUTING 增「分层与复用 / 先钉后拆 / 契约三件套 / 文档单一
  事实源」四节 + AGENTS.md 工程纪律速查
- **F-036** .gitattributes = `* text=auto eol=lf`（R8 修正：仓本全 LF，
  renormalize 恒 no-op；autocrlf 检出假象定性）
- **F-037** PR 模板补契约三件套自查行
- **F-038** 契约 fixture 入库 `.workbench 最小合法样例进 tests/fixtures/`
- **F-039 / F-040** 真实 fixture 即时抓到 README 示例单数 pattern 非法
- **F-034** README 账目同步：路线图撤下已收口 F-021~F-024 改列 F-031 / F-032
  实况；特性条去写死用例数；效果预览 JSON 加注 0.2 时期实录
- **66ca43f** README 新增 Windows 首次跑测试告警说明（GBK 乱码是 F-020 诚实
  化设计被 Windows 终端解码失败，工具本身 OK）

### 用户署名 + 仓配置

- 用户署名重写 14 commit（`filter-branch` 用户身份统一，详 release notes
  账本说明节）`xujiujiu0628(noreply)`
- 仓内 git config 配上用户身份
- 公开仓元数据：关 is_template / Projects；开 secret_scanning /
  push_protection / dependabot_security_updates（9-04 同期）

### 已知遗留（已登记）

- **F-031** Linux 真机路径整体未验证
- **F-032** serial_mux socat 限制按实情声明
- ESP32 接入立项暂缓（无目标板，路线图决策 esptool + probe-rs 仍有效）

---

## Unreleased — 2026-09-03（分层前时长画像，F-050）

- **F-050（分层前时长画像 / verify step-level timing，feat+test）**: 9-02
  方案四-4。"分层"前**先做时长画像**——不拍脑袋切层，用数据驱动。
  处置=双轨：① verify.py 每个 step 入口加 `t0 = time.time()` 出口写
  `step_info["duration_sec"]`（F-046 旧测试同步兼容——只追加字段）；
  ② 新工具 `scripts/duration_profile.py` 读 `.workbench/state/
  checkpoints.jsonl`（F-047 落盘）+ `result.steps.*.duration_sec` 聚
  合每个 step 的 min/p50/p95/max/sum/占比。`--demo` 跑 mock 数据自检；
  无真机场景下报告**透明标注**"非真机表现"——真机一跑数据自动真实化。
  mock 示意（典型单次真 verify）：**capture 67% 主导、build 21%、flash
  7%、physical_gate 3%、analyze 1%**——给"分层"决策的数据信号：捕获
  独立（占 67%）最大收益，analyze 单独跑不划算（启动开销比它大）。
  `tests/test_duration_profile.py` 14/14 绿（读 jsonl 3 + 聚合 1 + 百
  分位 4 + summarize 2 + CLI 4），全量 **258/258 绿**（skipped=1 仍
  F-026 opt-in）。对你 verify 的影响：每次跑 verify 多记 4 个
  `duration_sec` 字段（追加，向后兼容）；release audit 后续可按
  `checkpoints.jsonl` 看趋势（"最近 N 次 capture p95 涨了 30%"）。

## Unreleased — 2026-09-03（覆盖缺口 lint 取代行数红线，F-049）

- **F-049（scripts/ 覆盖缺口 lint 取代行数红线，feat+test）**: 9-02 方案
  四-3。**仓内此前根本没有"行数红线"——只在 memory 里有方案意图，本
  次按意图真做出工具**。行数是假命题：一个 200 行 const array 和一个
  200 行状态机风险天差地别；工程师为过红线拆文件反而劣化可读性。覆盖
  缺口才是真问题：工程师加新模块忘了给测试加 hook，PC 测试编译过但
  路径没测到，要等真机复现才发现。新工具 `scripts/coverage_lint.py`
  用 AST 扫 `tests/test_*.py` 的 import / from-import，收集所有引用
  的模块名；列 `scripts/` 下"未被任何 test 引用"的 .py 文件：
  ① 默认模式仅报告 (exit 0)；② `--strict` 发现未覆盖 exit 1 (CI 门
  禁用)；③ `--json` 机器可读；④ `legacy/` 目录豁免（F-029 退役 keil
  桥不强制覆盖）；⑤ `coverage_lint.py` 自身豁免（工具自检）。真仓
  实测发现 **13 个未覆盖文件**（cube_to_keil / gen_periph / openocd
  系列 5 个 / serial 系列 6 个）——CI 门禁开了就能早期抓。`test_
  coverage_lint.py` 13/13 绿（AST 解析 6 + 文件配对 4 + CLI 3），
  全量 **257/257 绿**（skipped=1 仍 F-026 opt-in）。对你 review /
  release 流程的影响：新增"覆盖缺口"作为可选门禁（默认不开启），
  行数从此**不再**作为任何 release 判据。

## Unreleased — 2026-09-03（doctor 体检扩 fixture 维度，F-048）

- **F-048（doctor 体检接入 fixture 状态检查，feat+test）**: 9-02 方案四-5
  （P0 余 2 单之一）。当前 doctor 只查工具链（gcc/openocd/make/SWD），
  不查 fixture；fixture 漂移是嵌入式测试最隐蔽的雷（PC 测试 PASS 真
  机挂）。处置=把 `tests/fixtures/contract/` 体检接到 `doctor_report`：
  ① **在场性**：config.json / expectations.json 缺失 → status="fail"；
  ② **漂移检测**：用 sha256 对比本地 vs 仓库 main 版（`git show main:...`
  不污染工作树），漂移 → status="warn" + 列出 mismatches 字段名；
  ③ 状态聚合进 `summary["fixture"]`（与 tools/swd 平级）。`_print_doctor`
  新增 fixtures 行（带 drift / missing 备注）。`fixture_health()` 接
  `skip_drift_check` 参数（测试场景：占位时显式跳过 git 调用，不破
  "占位不跑子进程" 守卫）。`test_doctor.py` 旧 `test_structure_and_
  summary_consistency` 同步加 fixture 计数（向后兼容：fixtures 缺失时
  行为不变）。9/9 新测（`test_fixture_doctor.py`）+ 全量 **253/253
  绿**（skipped=1 仍 F-026 opt-in）。对你 doctor 命令的影响：`--doctor`
  默认开启漂移检测（轻量 git show，秒级），`--doctor --json` 多了
  `fixtures` 字段 + `summary.fixture` 子项。

## Unreleased — 2026-09-03（进度台账，F-047）

- **F-047（verify 进度台账可重放证据，feat+test）**: 9-02 方案四-2。当前
  verify.py 跑出结果只落 feedback_db（校准用），不存 commit 锚点；事后
  无法回答"v1.1.0 tag 之前最后一次 PASS 是哪天哪个 commit"。处置=双写：
  ① `.workbench/state/checkpoints.jsonl` 追加台账（8 字段：ts/git_head/
  git_branch/status/duration_sec/origin/step_keys/contract_hashes，给审计
  链）；② `state.json["last_checkpoint"]` 覆盖（与 jsonl 末行同步，给消费
  方读"上次状态"）。`_git_head()` 隔离 git 调用，失败回空字符串而非抛
  （非 git 工程 / git 不可用）。主流程在 `_log_feedback_event` 之后
  `_output` 之前调一次 `record_checkpoint`；落盘失败不阻断（审计非门禁，
  stderr 告警即可）。**注意：当前 main() 只在正常出口落台账，早退路径
  （build_failed/flash_failed/capture_failed）不落——这是已知覆盖缺口，
  下次按需要补**。`record_checkpoint` / `_git_head` 单元 7 + main 集
  成 1，共 8/8 绿；全量 **252/252 绿**（skipped=1 仍 F-026 opt-in）。
  对 release audit：以后查"某 tag 之前最后一次 PASS"= `grep checkpoints.jsonl`
  + 按 ts/commit 过滤，零人工翻 git log。

## Unreleased — 2026-09-03（HIL 入口可追溯，F-046）

- **F-046（HIL 任务入口可追溯到 schedule/dispatch，feat+test）**: 9-02
  方案四-1。用户拍板 HIL 范围=flash+capture（build 是 PC 端不算，整流水线过
  宽）；默认 `task_origin=manual` 兼容现有 VS Code 直接调子工具（build/flash/
  debug 不走 verify.py，零影响），新增 `--task-origin {manual,schedule,dispatch}`
  与 `--require-schedule-origin` 旗标；开启硬卡时 manual 拒绝并 exit 2（区别
  于 0=成功/1=失败）；每次执行把 origin 写入 `result.steps.{flash,capture}.origin`
  并追加 `.workbench/state/audit.jsonl` 一行 JSON（ts/origin/step/status/command）
  ——台账是审计而非门禁，落盘失败不阻断主流程。`enforce_hil_origin()` + 
  `append_audit_entry()` 单元测试 10 + main 集成测试 3（mock step_flash / 
  _step_capture_rtt 验证守卫真的在 flash 前生效）；全量 **244 全绿**
  （skipped=1 仍 F-026 opt-in 活跳）。对你 VS Code 工作的影响清单：手动
  build/flash/debug 零影响；手动 verify 放行并打 `origin: "manual"` 标记，
  release audit 一眼可辨手动 vs CI 攒的 PASS；CI/release 门禁脚本加
  `--require-schedule-origin` 即可拦截手动跑。

## Unreleased — 2026-09-02（防腐纪律成文 + 换行符策略固化 + 契约 fixture，F-035~040）

- **F-035 登记+处置（成熟纪律仅靠惯例维持，docs only）**: 长期防腐方案三轮源码分析
  判定——本仓不缺防腐机制，缺机制覆盖面与成文化："先钉后拆"（F-029 六 Task 全程
  演练）、"先红后绿"（建仓 fix 一贯执行）、"复用不复制"（runtime_common 已建但
  "脚本自含"惯例未退役，22 同名符号三份存留的根因由其 docstring 自述）、文档单一
  事实源（F-034 亲踩）——全部只靠惯例与 commit message 传承，下一双手（含代管
  智能体）未必接得住。处置=把已兑现实践成文，不引入新流程：
  ① CONTRIBUTING 新增四节「分层与复用」（五层图+三条可机检 import 禁令+脚本自含
  退役+落层决策表）、「行为保持型重构：先钉后拆」、「契约变更三件套」、
  「文档同步（单一事实源）」，「测试与 PR 纪律」补先红后绿与注释 F 编号可追溯条；
  ② AGENTS.md 加「工程纪律速查」（执行侧摘要八行；明令与 CONTRIBUTING 分歧以
  后者为准——成文纪律的同时不制造新的双权威）。无代码改动；全量 **215 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-036 登记+处置（R8 换行符策略固化，chore，含方案判据修正）**: 方案基线判
  「三态并存、需一次 renormalize」定性有误——`git ls-files --eol` 实证索引区
  94/94 blob 本就统一 LF，三态只是本机 `core.autocrlf=true` 的检出态假象，
  `git add --renormalize` 实为恒零 diff 的 no-op。处置=新增 `.gitattributes`
  （`* text=auto eol=lf`，仓库自身固化"检出恒 LF、入库自动归一"，不再依赖各机
  autocrlf 个人设置；当前零二进制，不预写 binary 规则，未来误判按
  `*.<ext> binary` 逐条补），本地工作树强制重检出收敛 95/95 全 LF。无代码改动；
  换行翻转行为零影响，全量 **215 全绿** 两跑实证（skipped=1 仍 F-026）。
- **F-037 处置（契约三件套进 PR 必经表单，chore）**: F-035 成文的「契约变更
  三件套」只活在 CONTRIBUTING 正文，靠"记得去读"生效；`.github/
  PULL_REQUEST_TEMPLATE.md` 检查清单补一条自查项（同 commit 契约钉 /
  CHANGELOG 契约变更段 / toolkit_min_version 评估，不适用须注明），使规则
  进入每次提 PR 的必经表单——单人项目里"清单即评审"。纯模板文字，零代码；
  全量 **215 全绿**（skipped=1 仍 F-026）。

- **F-038 登记+处置（契约 fixture 入库，test+docs）**: `tests/fixtures/contract/`
  收录 .workbench 契约最小合法样例（config.json + expectations.json），期望条目
  覆盖全部九字段（id/desc/texts/patterns/capture_group/min/max/xfail/xfail_reason），
  test_contract_fixtures 三关验证 —— lint 全绿（唯一 warning=xfail 提示，F-026 口径）/
  loader 能吃（verify.load_config + wb_runtime.load_project_config + load_expectations）/
  四态判定语义（全信号 pass+pass+xpass 且 xpass 强制判红、缺 TODO xfail、低于下限
  fail 带 min 细节）；config 字段另钉与 README 公示值逐键一致。咬合验证：fixture
  min/max 对调 → E9+语义两例红 → 还原 → 绿。schema 演化时 fixture 同步改，diff 即评审点。
- **F-040 登记+处置（README 示例契约非法，docs，fixture 即发现）**: 「5 分钟上手」
  第 2 步示例 FR-ADC-02 用单数 "pattern" 键，而 loader 与 lint 均只认复数 "patterns"
  非空数组（load_expectations "texts 与 patterns 须二选一" 拦截）——照抄示例的用户在
  verify 首步即收到 "期望清单非法"。红证=按示例原样构造实测 loader 拒绝；处置=README
  示例改复数（与 fixture 同形，修后示例块实测 loader 3 条 + lint 零错）+
  test_singular_pattern_key_rejected 钉死单复数差异防回潮。教训归因：契约样例此前
  只在文档里"展示"，从未过 loader/lint 回路 —— F-038 入库回路后当轮即抓到本例。
- **F-041 登记+处置（--doctor 环境预检 + swd_probe 下沉共享层，feat）**: 长期防腐
  方案 §6.1 建议的工具链环境矩阵自检落地——`verify.py --doctor` 打印 toolkit/Python/
  machine.json 四键/gcc/openocd/make/SWD 连通性后退出，报障随 issue 附
  `--doctor --json` 输出，把"环境不同"类无效往返消灭在入口。关键设计：
  ① **swd_probe 从 release.py 私有实现下沉至 openocd_runtime**——发布门禁 G0.5 与
  doctor 共用同一命令与判据，防两处口径再漂移；对象同一性
  （`openocd_runtime.swd_probe is release.swd_probe is verify.swd_probe`）由
  test_doctor 钉死；② **占位路径永不执行**——machine.example.json 的 `<...>` 占位值
  绝不触发子进程（mock 守卫钉死，触发即 AssertionError）；空/占位 → skipped 如实标注；
  ③ doctor 分支先于工程发现，不依赖 .workbench 工程；machine.json 缺失走 load_machine
  回退链并如实标 mode=fallback；④ 退出码恒 0——诊断报告，不是门禁；
  ⑤ 版本行 stdout/stderr 合并取首行（OpenOCD 版本打印在 stderr 的实情）。
  伴随微调：swd_probe attempts 参数化，末次失败不再空转 sleep；doctor 传 1 做单次
  快探、门禁 G0.5 保持 3 次重试（语义不变，test_doctor 双向钉死）。
  实测：本机真 machine.json 三工具 ok、无板时 swd=fail 如实报（非伪装）；全量
  **231 全绿**（skipped=1 仍 F-026 opt-in 活跳）。

## Unreleased — 2026-09-01~02（代管 R3：跨平台回收 + 外围模块补齐入账；次日 F-029 整车收口）

- **F-027 登记+修复（P0，TDD 先红后绿）**: `verify.py::_step_capture_rtt()` 裸用
  `subprocess.CREATE_NEW_PROCESS_GROUP`——该常量仅在 CPython `if _mswindows:` 分支内
  绑定（subprocess.py:80-82 实证），Linux/macOS 上属性访问即 AttributeError；且 README
  「5 分钟上手」第 1 步示例正是 `"backend": "rtt"`，照抄的 Linux 用户首次真机运行必崩。
  默认 semihosting 走内联路径不经过该行，故长期未暴露。仓库其余 4 处同类常量
  （openocd_gdb/itm/semihosting/telnet）全部带守卫——属遗漏，非设计选择。修复=搬既有
  惯用法 `... if sys.platform == "win32" else 0`（提出重试循环外，单次计算）。
  回归钉 `test_platform_guards.py` 静态判据：裸用 Windows-only subprocess 常量须与守卫
  同行（`getattr(subprocess, …, 0)` 形态构造性安全豁免；legacy/ 不入扫描）——修前
  红证仅命中 verify.py:134 单点，修后绿；全量 **183 全绿**（skipped=1 仍为 F-026）。
- **F-028 登记（孤儿代码，待拍板，未动刀）**: `verify.py::step_capture_semihosting()`
  全仓零调用（仅命中定义处），其唯一下游为 `OPENOCD_SEMIHOSTING` 常量（verify.py:46），
  该常量唯一使用点即此死函数（:363）——死链完整终止于 `openocd_semihosting.py`
  （544 行，自带 `__main__` 独立 CLI 形态，未入 README 工具表，零测试覆盖）。实际生效的
  semihosting 是 verify.py 内联实现（:1145 注释自述"不走复杂脚本"）；verify.py:16 头图
  仍写 Capture→openocd_semihosting.py，同属陈旧。
- **F-028 处置（同日拍板，整链删除）**: 维护者选定删除方案——`git rm
  openocd_semihosting.py`（544 行）+ 死函数 `step_capture_semihosting()` + 死常量
  `OPENOCD_SEMIHOSTING`，头图第 4 步改写为"verify.py 内置双路: semihosting 内联 |
  rtt"；RTT 段首两处与内联 semihosting 分支内共三处悬空注释同步收口（末处保留
  "曾有其物，git 史可回放"记号）。删除前后全仓 grep 零代码引用；183 全绿不变。
- **F-030 登记（头图陈旧，维护者拍板下轮顺手修）**: verify.py 头图流程第 1/2 步仍写
  Build→keil_build.py / Analyze→keil_analyze.py——Keil 已于 2026-08-28 退役入 legacy
  （:42-45 实证：默认后端 `builder=gcc`，Keil 桥仅显式配置时按需唤起）。修法=两行
  改写为 GCC 默认 + legacy 桥注记，与 :43 口径一致；随下轮（F-029 契约统一或 F-026
  tempfile 化）顺手刷掉。
- **F-030 处置（同轮提前带走）**: 头图 1/2 步已刷——Build→gcc_build.py（默认，
  builder=keil 显式配置时唤起 legacy 桥）；Analyze→gcc 路径直传 build metrics，
  keil 路径走 legacy 知识库（口径对照 step_analyze 实现）。
- **F-033 处置（收口完成）**: 三分支 `git branch -d` 删除（-d 自带"仅认可已合并"
  保险；删除输出留 8afd8dd/9cadade/0104dcb 三 SHA 供 reflog 回放）。
- **F-029 登记（重复度量化，附限定条件）**: 三份 runtime（wb 379 / openocd 354 /
  serial 515 行）共有 22 个同名符号、三份合计 633 行、相对最大单份冗余 406 行
  （≈430-450 区间下沿，判据=同名符号行数并集）。**非纯复制，是同源分叉**：
  `make_result` serial 侧为 `success: bool` 位置参，wb/ocd 为 keyword-only `status: str`；
  `parameter_context` 三处签名各不相同——机械去重必破坏调用方。且
  test_writeback_guards.py:28 以 `RUNTIMES=[wb, ocd, serial]` 参数化把三形态钉进测试，
  合并时测试须同步改。路线：先统一契约，后谈提取公共模块。
  **计划已交**（`docs/superpowers/plans/2026-09-01-f029-runtime-dedup.md`）：
  AST 两两比对实测重定分桶——5 字节同 / 7 仅 docstring 差 / 4 真分叉含同名异物 /
  4 路径策略 / 2 机制分叉；登记期"serial make_result 契约分叉"经实测修正为
  **入参签名分叉、输出本就 status 同族**（可适配器并轨），`make_timing`/
  `parameter_context` 才是同名异物；另撞出 Windows pre-epoch 时间戳 OSError 边界。
  施工按 6 Task TDD 推进，特征钉先行冻结 wire。
- **F-029 处置（2026-09-02 整车完成，6 Task TDD 全绿）**: 新建共享层
  `scripts/runtime_common.py`（295 行 / 25 规范符号，仅 stdlib、不 import 三 runtime 防环；
  与"路径解析"定位的 `wb_common` 互不渗透），三 runtime 以再导出/薄壳维持 `mod.X`
  调用面，17 个工具消费方零迁移。**AST 净账**（docstring 无关判据）：同名同形重复行
  浪费 **195 → 4**（余 4 行为 wb/serial 序列化钩子薄壳，同形系设计使然）、同名异形
  12 → 6 组全部显式留份 + docstring 钉；runtime 本体规模 wb 391→187、ocd 354→158、
  serial 515→404。**三处订正**（对登记期分桶表）: ① `save_workspace_state`/
  `update_state_entry` 非"纯 docstring 差"——**wb==serial 落盘序列化**（绝对路径→
  workspace 相对 POSIX）、ocd 原样存，是真 wire 语义分叉，以 `serialize` hook 注入保
  三家形态；② serial `normalize_path` 非 wb 版超集（相对输入不 resolve），裁决留本地；
  ③ 计划"ocd/serial save_local_config 补守卫"项**撤销**——环境级配置一 skill 一文件、
  整写不读旧档，天然无损坏丢键风险，守卫缺位系正当设计（裁决钉锁形）。
  **留份判定**: `make_result` 双契约（serial `success:bool` 位置参冻结 + 空 details
  省略/原样透传，薄适配器转调规范版，六 serial 工具输出字节兼容）；`resolve_param`
  三家源标签/层级/normalize 锚定/异常策略不可调和，**整组留三份**——F-029 系契约
  统一而非为去重率强并。配套: `tests/test_runtime_contract.py` 23 例特征钉+裁决钉
  先按现实绿再施工（T1 前置），F-023 pid 用例 patch 目标按计划预案改 `runtime_common.os`
  并记因；随实现搬出收口 STATE/PROJECT 死常量与两处 sys 死导入。全量 **215 全绿**
  （skipped=1 仍 F-026 opt-in 活跳）。
- **F-021/F-022/F-023 处置（原子写收口包，TDD 六签先红后绿）**: 三件同族打包。
  F-021=`wb_runtime.save_local_config` 补 F-020 同款损坏拒写守卫（读改写族；
  openocd/serial 侧同名函数为整写语义不在族内，维持不动）；F-022=新增共享工具
  `wb_common.atomic_write_json`（pid tmp + 强制 LF + 自动建父目录），
  `error_db_grow` 两处与 `release.py` 记录写三处裸 `open('w')+json.dump` 全部并入，
  并落静态防回潮钉（两脚本内 open-w 后 3 行内 json.dump 即违例）；
  F-023=三份 runtime `save_json_file` tmp 名改 `<file>.<pid>.tmp` 杜绝双进程互顶
  （按脚本自含惯例保留三份拷贝，契约统一留 F-029）。新增 5 例，
  全量 **188 全绿**（skipped=1 仍 F-026）。
- **F-024 处置（R7 双布局认路，先红后绿）**: release_audit R7 比对路径由硬编码
  `.workbench/*` 改为 `.workbench`→`.embeddedskills` 顺序双认（首中即停，优先序与
  verify.contract_hashes 的 marker 序一致，杜绝"哈希取 A 路、比对找 B 路"假错位）；
  两布局均未命中才 warn 且消息改为"两布局均不可得"。红证=新例
  `test_embeddedskills_layout_contract_matched` 修前 warn 修后 pass；
  篡改/搬移负例 15/15 无波损。
- **F-031 登记（本轮施工）**: Linux 真机路径整体未验证——F-027 修掉的是"已知崩溃点"
  而非完成验证；README 自述"真机构建路径未验证、欢迎报告"，CI（ubuntu）只跑 mock 套件，
  进程终止/信号/创建标志类平台差异仍属盲区。本轮补 `_step_capture_rtt()` 的
  mock-Popen 平台派发单元钉（Linux 模拟必传 creationflags=0——即 P0 崩溃类），
  真机 Linux 冒烟清单仍留社区/后续。
- **F-031 处置（派发钉落地，咬合验证）**: `RttSpawnFlagsPlatformTests` 两例——
  Linux 模拟断言三试全传 0、win32 模拟断言传真实常量（本机无常量则 skip），
  顺带钉住 3 重试骨架与"进程即死必如实 error"。咬合验证：临时回退 F-027 修法
  → 钉转红 → 还原 → 转绿，verify.py 字节回滚（diff 仅测试文件）。与 F-027
  静态钉成对：属性级 + kwargs 级双层防线。
- **F-032 登记+处置（限制声明，含登记语订正）**: `serial_mux.py` PTY 虚拟串口层硬
  依赖 socat——施工时核实比登记更严重：`which("socat")` 检查在 `start_mux()` 最前
  无条件执行，**无 socat 则整个 mux 起不来**（并非登记初稿所写"另两层不受影响"，
  该不实表述已随本条订正）。错误消息与模块头图同步改为实情：PTY 层 Linux/macOS-only、
  Windows 不支持；"与 PTY 解耦（--no-pty）"列为后续增强，未实现前不按部分功能规划。
- **F-026 处置（冒烟 tempfile 化，同轮提前带走）**: 删除硬编码维护者路径占位符
  （历史重写后已死）；改双段——合成全字段清单（texts/patterns+capture_group+
  min-max/xfail+reason 三条目，钉"xfail 提示是唯一合法 warning"）任何机器任何
  检出恒跑；真档冒烟能力保留为 `ETK_SMOKE_EXPECTATIONS` 环境变量 opt-in（本机
  实测指向 adc-oled 真清单通过，2/2 无跳）。全量 **192 全绿**；skipped=1 语义
  变更：不再是占位符死跳，改为 opt-in 主动跳过。
- **F-033 登记（本轮处置）**: handoff 三分支（zcode-20260830 / zcode-r2-20260830 /
  r2-reconcile-20260831）`git branch --merged master` 全部命中——R2/R3 换回流程遗留，
  去留自 R2 挂账至今。本轮 `git branch -d` 收口删除（-d 自带已并入保险）。
- **F-034 登记+处置（README 账目漂移，docs only）**: README「路线图」仍列
  F-021~F-024 为已知遗留，但四者已分别经 `bd37564`（原子写收口包）与 `66ef73f`
  （R7 双布局认路）处置完毕——该节自述"登记在册，不藏"，却把已修项继续登记为未修，
  且未反映新处置的 F-025~F-033，外部审查者会照单去查已不存在的项。
  处置=撤下已收口四项，改列 **F-031**（部分闭合：Linux 真机路径整体未验证——
  F-027 只修了"已知崩溃点"，进程终止/信号/创建标志类平台差异仍属盲区，已补
  mock-Popen 平台派发钉）与 **F-032**（限制声明：serial_mux PTY 层硬依赖 socat、
  Linux/macOS-only，`--no-pty` 解耦未实现前不按部分功能规划）；多 MCU 方向补前置项
  （interface/target cfg 硬编码 `verify.py` 7 / `release.py` 2 / `hardfault.py` 2 处）。
  另处置两处表述：① 特性条原写"170+ 例"——**违反本仓 CONTRIBUTING「例数以实跑为准，
  勿在文档写死数字」**，且与实际（215）的差距随修复持续拉大，改为不写死数字、
  指向实跑命令；②「效果预览」JSON 的 `"toolkit_version": "0.2"` **保留不改并加注**
  ——该段标注"全文真实可回放"，是 0.2 时期真机实录，改写版本号等于篡改可回放记录，
  与 F-003 归因诚实原则相悖；要反映当前版本须真机重跑整段替换（待有板时进行）。
  全量 **215 全绿**（skipped=1 仍 F-026 opt-in 活跳）。

## Unreleased — 2026-09-01（开源准备：社区门面补全 + 历史脱敏重写）

- **社区门面补全**: 新增 `CODE_OF_CONDUCT.md`（Contributor Covenant 2.1 中译）/
  `SECURITY.md`（私下报告渠道 + 响应时限 + 硬件免责）/
  `.github/PULL_REQUEST_TEMPLATE.md`（对齐 CONTRIBUTING 测试纪律）；
  `.gitignore` 补全标准清单（虚拟环境/依赖/日志/DB/系统/IDE）；README 加
  License/Python/Platform 徽章与「贡献」入口。
- **敏感信息扫描建档**: `SENSITIVE_FINDINGS.md`（15 类凭证模式全零）与
  `OPENSOURCE_READY.md`。
- **历史脱敏重写（git filter-repo × 两轮，决策反转）**: 对 0.3 节
  "不重写 git 历史"的反转——公开前洗清个人 Windows 用户名（27 处，全部
  Users 路径形态，定长 lookbehind 零误伤）与工作区盘符路径（三形态统一
  映射 `<工作区根>`）。**坑（登记）**: `--replace-text` 不作用于 commit/tag
  message，首轮漏 1 处，二轮 `--message-callback`/`--tag-callback` 补齐；
  终验（log -p + 全部 %B + tag contents）零残留。**本账目与 docs 中引用的
  重写前短 hash 全部失效**——重写前完整 commit 图封存于
  `../archive/embedded-toolkit-prehistory-20260901.bundle`，clone 该 bundle
  可按旧 hash 回放全部证据链（0.3 节括号内 hash 均指旧图）。
- **守卫判据适配（重写伴随，本次唯一代码改动）**: `test_failure_hints.py`
  静态守卫的断言目标被重写洗成占位符→恒真失效，改通用盘符判据
  `[A-Za-z]:[\\/]{1,2}(Users|claude)` 恢复"防硬编码回潮"原语义。
- **F-025 存量缺陷登记**: `test_cli_exit_codes_and_json` 在 Windows 非 UTF-8
  控制台失败（子进程 GBK 撞 utf-8 解码）；bundle 基线对照复现 → 与本轮操作
  无关，CI（ubuntu）恒绿。（登记原文留档，修复见下条。）
- **F-025 修复（同日，TDD 先红后绿）**: `expectations_lint.main()` 起手强制
  stdout/stderr UTF-8（惯用法对齐 `verify._output`，stderr 一并——人类模式
  错误报告同为中文）；新增回归钉 `test_json_output_utf8_regardless_of_console`
  将子进程环境强制 `PYTHONIOENCODING=gbk` 仍断言 --json 输出为合法 UTF-8 JSON
  ——修前以同款 0xce 崩溃证红、修后证"随脚本不随环境"；全量套件 **182 全绿**
  （skipped=1 为 F-026）。
- **F-026 联动现状**: `test_expectations_lint.py` 真档冒烟路径字面量随重写
  变占位符，本机亦恒跳过（skipped+1）；tempfile 化已无历史包袱，列下轮。
- **F-5 时间线登记**: Events API 显示仓库曾于 2026-08-26 公开一次（转私时点
  不可考），9/1 复转 Public 与脱敏推送最坏重叠约 20 分钟——低危残留仅入账，
  不向 GitHub support 提 purge（推理见 SENSITIVE_FINDINGS F-5）。
- **v0.3 Release 追加账本说明节**: 维护者 08-31 手写正文保留原文（含已被
  反转的"历史不重写"策略句，不删），文末拼接追加节声明反转、旧 hash 回放
  指引与已知事项索引；description + 10 topics 经 gh 落地。

## 0.3 — 2026-08-31（开源门面，master）

- **machine.json 出库+回退链**: 新克隆无 machine.json 时 `load_machine` 回退
  入库模板 `machine.example.json` 并一次性警告（测试/离线工具直接可跑；占位
  路径被真机用到以自解释 FileNotFoundError 报错，F-011 显式原则）；gcc_build
  局部副本改委托单一实现；machine.json 转本机维护不再入库（1605e92、4e953c4、
  6c32584）。
- **个人路径中性化**: 历史文档 11 处 `C:\Users\<用户名>` 形态清洗为
  `%USERPROFILE%`/`<用户名>` 写法；不重写 git 历史（约 30 个 git show 证据链
  与 v0.2 tag 指向依赖现有 commit 图，理由见 commit body）（399657b）。
- **提示去硬编码**: verify 失败现场 agent_hint 随 TOOLKIT_ROOT 推导、gen_periph
  生成物注释改仓相对命令，含 4 例回归与源码静态守卫（23d288f）。
- **门面套**: LICENSE(MIT) / requirements.txt(仅串口族 pyserial) /
  GitHub Actions CI(ubuntu × py3.10/3.12，刻意不建 machine.json=陌生人路径
  金丝雀) / CONTRIBUTING + ISSUE_TEMPLATE / README 全文重写。
- Python 下限如实定 **3.10**（verify/hardfault/feedback_db 等使用 PEP 604
  联合类型且无 future import）。套件随门面工作增长，例数以实跑为准。

## 0.2 — 2026-08-30（代管 R2，分支 handoff/zcode-r2-20260830）

- **F-018**（原报告编号 F-015，换回对账重排，见
  `docs/handoff/2026-08-31-r2-reconcile-notes.md`）发布记录绑定契约哈希: verify 输出 `contract_hashes`
  （config/expectations 字节级 sha256），release 写入发布记录，
  release_audit 新增 **R7**（对照 `git show <git_head>:` 重算比对，
  错位=fail，R7 之前旧记录=warn）——关闭"G1 期间改契约再还原"的取证盲区
  （34a96e5）。
- **F-019/F-020**（原报告编号 F-016/F-017，换回对账重排）写回型工具损坏清空家族修复（三份 runtime 拷贝同修）:
  `save_project_config` 损坏**拒绝写回**；`update_state_entry` /
  serial_mux 读改写损坏**隔离 .corrupt 后重建**；`save_json_file` 改
  **原子写**（.tmp + os.replace，杜绝并发撕裂读）；error_db_grow 知识库
  损坏明确拒绝写入；gcc_build config 写回抽 `merge_gcc_config`
  （351e021）。
- 新工具 **expectations_lint.py**（D 项）: verify.load_expectations 规则
  离线化 E1~E9，含 verify 不查的 E9 `min>max` 结构矛盾；两现役工程真档
  冒烟 CLEAN（10507bd）。
- **C 项** 零覆盖模块补测 21 例: phase_minus_one / rm_lookup /
  token_stats / svd_to_json（cc54e45）。
- 文档对齐: 本 CHANGELOG 新建；AGENTS.md / HANDOFF-AGENT.md 过期计数
  （47 测试/28 脚本）改为动态表述；HANDOFF-AGENT.md §2 补 #10/#11
  防重报条目。

### 换回对账增补（主控，2026-08-31）

- **外部核查**: fresh-check 无上下文对抗审计判"通过但有保留"（C0/H1/M1/L2，
  落账 fc_20260831_122115+0800）；修复与回归独立复现成立，纪律无违例。
- **High-1 处置**: R2 分支起点偏移确认（父链起点 9997ac2 ≠ 宣告基线链）→
  编号重排 F-018/019/020（原编号与 1819e18 冲突）、findings-r2 归因更正、
  §2 勿重做清单合并为 13 行、新工具 hash 重放对照，详见
  `docs/handoff/2026-08-31-r2-reconcile-notes.md`。
- **遗留登记**: F-021 save_local_config 同族漏网 / F-022 三处非原子写 /
  F-023 固定 .tmp 并发尾洞 / F-024 R7 路径盲区（对账记录 §3，第三轮排期）。
- **换回协议升级**: 第 3 步纳入 expectations_lint 两工程秒检（采纳 R2 §六-3
  建议）；§5 上岗规矩新增"先核分支起点"（R2 教训回写）。
- 合入后套件基线 **172**（155∪106，master 净增 17 零丢失）；未跟踪
  .mcp.json（用户确认非本人添加）移出至 archive/mcp-from-toolkit-20260831/。

## 0.1.x — 2026-08-30（代管 R1，分支 handoff/zcode-20260830）

- **F-001**（Critical）feedback_db 首次落账死锁——button-toggle 建成以来
  反馈零落账（4866fb5）。
- **F-002** config 容错 / **F-003** 采集超时诚实化（部分输出回收+失败
  现场落盘，待真机终判）/ **F-004** 落账三态留痕 / **F-005** hardfault
  默认 map 自动发现（1baeed2、11eb319）。
- **F-014** 校准库损坏容错（.corrupt 隔离 + 空库重建）（afc7265）。
- **F-006/007/008/012** Low 清理组；F-009/010/011/013 记录不修（fa5efb4）。
- 新工具 **release_audit.py**（M-3）: 发布记录事后审计 R1~R6（eb1e4c9）。
- **主干补充**（主控，master，首轮换回后当日——R2 分支未及见的 8 commit）:
  hardfault 三层全修 symbols 0→126 真机坐实（920e187）；F-015 workspace 跟随
  --project / F-016 采集窗进契约 / F-017 load_project_config 段语义双重错误
  （1819e18，106/106）；插板终判四项全绿（d052060）；A-02 哈希举证对账（f4b5d4f）。
