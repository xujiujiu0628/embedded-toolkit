# Changelog

格式约定: 每条含发现编号（代管期 findings 编目）与证据 commit。当前版本以
`VERSION` 文件为准（`wb_common.toolkit_version()` 读取）。

## Unreleased — 2026-09-01（代管 R3：跨平台回收 + 外围模块补齐入账）

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
- **F-029 登记（重复度量化，附限定条件）**: 三份 runtime（wb 379 / openocd 354 /
  serial 515 行）共有 22 个同名符号、三份合计 633 行、相对最大单份冗余 406 行
  （≈430-450 区间下沿，判据=同名符号行数并集）。**非纯复制，是同源分叉**：
  `make_result` serial 侧为 `success: bool` 位置参，wb/ocd 为 keyword-only `status: str`；
  `parameter_context` 三处签名各不相同——机械去重必破坏调用方。且
  test_writeback_guards.py:28 以 `RUNTIMES=[wb, ocd, serial]` 参数化把三形态钉进测试，
  合并时测试须同步改。路线：先统一契约，后谈提取公共模块。

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
