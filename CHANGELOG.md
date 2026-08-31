# Changelog

格式约定: 每条含发现编号（代管期 findings 编目）与证据 commit。当前版本以
`VERSION` 文件为准（`wb_common.toolkit_version()` 读取）。

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
