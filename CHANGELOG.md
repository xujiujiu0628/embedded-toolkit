# Changelog

格式约定: 每条含发现编号（代管期 findings 编目）与证据 commit。当前版本以
`VERSION` 文件为准（`wb_common.toolkit_version()` 读取）。

## Unreleased — 2026-09-02（防腐纪律成文：CONTRIBUTING/AGENTS，F-035）

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
